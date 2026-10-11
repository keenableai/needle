import itertools
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from needle.finance.models import Filing
from needle.finance.registries import SecClient
from needle.finance.sources import EdgarClient
from needle.haystack.models import SUITE_SPECS, DeepDoc, build_gold_row
from needle.haystack.projection import (
    MIN_DOC_CHARS,
    build_haystack_prompt,
    deep_excerpt,
    parse_haystack_reply,
    question_ok,
    syntax_query,
)
from needle.haystack.sources import FederalRegisterClient, WikiClient, wiki_url
from needle.scholar.sources import ARXIV_DOMAIN_QUERY, ArxivClient
from needle.shared.concurrency import bounded_gather
from needle.shared.llm import LLMClient
from needle.shared.sampling import dedupe_by, shuffle_indices

SEC_FORMS = frozenset({"10-K"})
SEC_SEED_ROWS = 1000
ARXIV_WINDOW_DAYS = (30, 3)
ARXIV_PER_DOMAIN = 60

SUITE_SEEDS = {"gov": 0x90F, "sec": 0x5EC, "wiki": 0x717, "arxiv": 0xA87}

DROP_STAT = {
    "fetch": "fetch_fail",
    "thin": "thin",
    "llm_error": "llm_errors",
    "no_question": "no_question",
    "rejected": "rejected",
}


@dataclass
class GenStats:
    candidates: int = 0
    rows: int = 0
    fetch_fail: int = 0
    thin: int = 0
    llm_errors: int = 0
    no_question: int = 0
    rejected: int = 0
    surplus: int = 0
    by_suite: dict[str, int] = field(default_factory=dict)


def _pick(items: list[Any], n: int, seed: int) -> list[Any]:
    return [items[i] for i in shuffle_indices(len(items), seed)[:n]]


async def _suite_rows(
    suite: str,
    candidates: list[Any],
    fetch_doc: Any,
    llm: LLMClient,
    *,
    per_suite: int,
    seed: int,
    hour_ts: datetime,
    doc_concurrency: int,
    stats: GenStats,
) -> list[dict]:
    spec = SUITE_SPECS[suite]
    stats.candidates += len(candidates)

    async def project(cand: Any) -> tuple[DeepDoc, str, str, str, int] | str:
        try:
            doc = await fetch_doc(cand)
        except Exception:
            return "fetch"
        if doc is None:
            return "fetch"
        if len(doc.text) < MIN_DOC_CHARS:
            return "thin"
        picked = deep_excerpt(doc.text, seed=seed, url=doc.url)
        if picked is None:
            return "thin"
        excerpt, depth_pct = picked
        try:
            reply, err = await llm.complete(
                build_haystack_prompt(doc, excerpt, spec=spec),
                max_tokens=1024,
                reasoning_effort="minimal",
            )
        except Exception:
            return "llm_error"
        if err is not None:
            return "llm_error"
        parsed = parse_haystack_reply(reply)
        if parsed is None:
            return "no_question"
        field_type, answer, question = parsed
        if not question_ok(question, answer, field_type, doc=doc, excerpt=excerpt):
            return "rejected"
        return doc, field_type, answer, question, depth_pct

    projected = await bounded_gather(candidates, project, concurrency=doc_concurrency)

    rows: list[dict] = []
    syntax_cycle = itertools.cycle(spec.syntax_cycle)
    for outcome in projected:
        if isinstance(outcome, str):
            setattr(stats, DROP_STAT[outcome], getattr(stats, DROP_STAT[outcome]) + 1)
            continue
        if len(rows) >= per_suite:
            stats.surplus += 1
            continue
        doc, field_type, answer, question, depth_pct = outcome
        syntax = next(syntax_cycle)
        rows.append(
            build_gold_row(
                suite=suite,
                field_type=field_type,
                value=answer,
                query_text=syntax_query(question, syntax, site=spec.site, published=doc.published),
                doc=doc,
                depth_pct=depth_pct,
                hour_ts=hour_ts,
                syntax=syntax,
            )
        )
    stats.by_suite[suite] = len(rows)
    return rows


async def _gov_candidates(fr: FederalRegisterClient, n: int, seed: int) -> list[dict]:
    rules = await fr.rules()
    return _pick(rules, n, seed ^ SUITE_SEEDS["gov"])


def _gov_fetcher(fr: FederalRegisterClient) -> Any:
    async def fetch(rule: dict) -> DeepDoc | None:
        text = await fr.document_text(rule["raw_text_url"])
        if not text:
            return None
        return DeepDoc(
            suite="gov",
            title=rule["title"],
            url=rule["html_url"],
            published=rule["publication_date"],
            text=text,
            doc_keys={
                "document_number": rule["document_number"],
                "agencies": rule["agency_names"],
            },
        )

    return fetch


async def _sec_candidates(sec: SecClient, n: int, seed: int) -> list[dict]:
    all_rows = await sec.tickers(0)
    return _pick(all_rows[:SEC_SEED_ROWS], n, seed ^ SUITE_SEEDS["sec"])


def _sec_fetcher(edgar: EdgarClient, seed: int) -> Any:
    async def fetch(row: dict) -> DeepDoc | None:
        filings = await edgar.filings(row["cik"], forms=SEC_FORMS, limit=10)
        if not filings:
            return None
        pick = filings[(seed ^ row["cik"]) % len(filings)]
        filing = Filing(
            cik=row["cik"],
            company=row["title"],
            ticker=row["ticker"],
            form=pick["form"],
            adsh=pick["adsh"],
            filed=pick["filed"],
            primary_doc=pick["primary_doc"],
        )
        text = await edgar.document_text(filing)
        if not text:
            return None
        return DeepDoc(
            suite="sec",
            title=f"{filing.company} {filing.form} filed {filing.filed}",
            url=filing.doc_url,
            published=filing.filed,
            text=text,
            doc_keys={
                "entity": filing.company,
                "ticker": filing.ticker,
                "cik": filing.cik,
                "form": filing.form,
                "adsh": filing.adsh,
            },
        )

    return fetch


async def _wiki_candidates(wiki: WikiClient, n: int, seed: int) -> list[str]:
    titles = await wiki.featured_titles()
    return _pick(titles, n, seed ^ SUITE_SEEDS["wiki"])


def _wiki_fetcher(wiki: WikiClient) -> Any:
    async def fetch(title: str) -> DeepDoc | None:
        got = await wiki.extract(title)
        if got is None:
            return None
        resolved, text = got
        return DeepDoc(
            suite="wiki",
            title=resolved,
            url=wiki_url(resolved),
            published="",
            text=text,
            doc_keys={"wiki_title": resolved},
        )

    return fetch


async def _arxiv_candidates(arxiv: ArxivClient, n: int, seed: int, now: datetime) -> list[Any]:
    from_date = (now - timedelta(days=ARXIV_WINDOW_DAYS[0])).date().isoformat()
    to_date = (now - timedelta(days=ARXIV_WINDOW_DAYS[1])).date().isoformat()
    papers: list[Any] = []
    for domain in ARXIV_DOMAIN_QUERY:
        papers.extend(
            await arxiv.search_domain(
                domain, from_date=from_date, to_date=to_date, max_results=ARXIV_PER_DOMAIN
            )
        )
    papers = dedupe_by(papers, lambda p: p.arxiv_id)
    return _pick(papers, n, seed ^ SUITE_SEEDS["arxiv"])


def _arxiv_fetcher(arxiv: ArxivClient) -> Any:
    async def fetch(paper: Any) -> DeepDoc | None:
        text = await arxiv.body(paper.arxiv_id)
        if not text:
            return None
        return DeepDoc(
            suite="arxiv",
            title=paper.title,
            url=paper.url,
            published=paper.published.date().isoformat(),
            text=text,
            doc_keys={"arxiv_id": paper.arxiv_id, "domain": paper.domain},
        )

    return fetch


async def run_generate(
    *,
    fr: FederalRegisterClient | None,
    wiki: WikiClient | None,
    sec: SecClient | None,
    edgar: EdgarClient | None,
    arxiv: ArxivClient | None,
    llm: LLMClient,
    suites: tuple[str, ...],
    hour_ts: datetime,
    now: datetime,
    per_suite: int = 15,
    oversample: int = 3,
    seed: int = 0,
    doc_concurrency: int = 8,
) -> tuple[list[dict], GenStats]:
    stats = GenStats()
    n = per_suite * oversample
    rows: list[dict] = []

    async def add(suite: str, candidates: list[Any], fetch_doc: Any) -> None:
        rows.extend(
            await _suite_rows(
                suite,
                candidates,
                fetch_doc,
                llm,
                per_suite=per_suite,
                seed=seed,
                hour_ts=hour_ts,
                doc_concurrency=doc_concurrency,
                stats=stats,
            )
        )

    if "gov" in suites and fr is not None:
        await add("gov", await _gov_candidates(fr, n, seed), _gov_fetcher(fr))
    if "sec" in suites and sec is not None and edgar is not None:
        await add("sec", await _sec_candidates(sec, n, seed), _sec_fetcher(edgar, seed))
    if "wiki" in suites and wiki is not None:
        await add("wiki", await _wiki_candidates(wiki, n, seed), _wiki_fetcher(wiki))
    if "arxiv" in suites and arxiv is not None:
        await add("arxiv", await _arxiv_candidates(arxiv, n, seed, now), _arxiv_fetcher(arxiv))

    rows = dedupe_by(rows, lambda r: r["query_id"])
    stats.rows = len(rows)
    return rows, stats
