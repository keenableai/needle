from dataclasses import dataclass
from datetime import datetime
from typing import Any

from keenbench.companyfill.registries import SecClient
from keenbench.finance.models import (
    FILINGDOC_SYNTAX_CYCLE,
    FILINGS_SYNTAX_CYCLE,
    Filing,
    QuarterFact,
    build_filing_row,
    build_filingdoc_row,
)
from keenbench.finance.projection import (
    MIN_DOC_CHARS,
    build_filingdoc_prompt,
    clean_filingdoc_query,
    filingdoc_query_ok,
    filingdoc_syntax_query,
    filings_query,
)
from keenbench.finance.sources import EdgarClient, quarterly_facts
from keenbench.shared.concurrency import bounded_gather
from keenbench.shared.llm import LLMClient
from keenbench.shared.sampling import shuffle_indices

DOC_OVERSAMPLE = 3
DOC_FORMS = frozenset({"10-K", "10-Q", "8-K"})
COMPANY_CONCURRENCY = 8
TIER_BOUNDS = (("mega", 0, 100), ("large", 100, 500), ("mid", 500, 2500))


def tiered_companies(all_rows: list[dict], per_tier: int, seed: int) -> list[dict]:
    out = []
    for name, lo, hi in TIER_BOUNDS:
        pool = all_rows[lo:hi]
        perm = shuffle_indices(len(pool), seed ^ lo)
        for i in perm[:per_tier]:
            out.append({**pool[i], "tier": name})
    return out


@dataclass
class GenStats:
    companies: int = 0
    filings_rows: int = 0
    facts_missing: int = 0
    doc_candidates: int = 0
    filingdoc_rows: int = 0
    doc_fetch_fail: int = 0
    doc_thin: int = 0
    doc_no_query: int = 0
    doc_rejected: int = 0
    llm_errors: int = 0
    errors: int = 0


async def _filings_rows(
    seed_rows: list[dict],
    sec: SecClient,
    *,
    fields: tuple[str, ...],
    per_company: int,
    quarters_back: int,
    seed: int,
    hour_ts: datetime,
    now: datetime,
    stats: GenStats,
) -> list[dict[str, Any]]:
    async def company_facts(row: dict) -> list[tuple[dict, QuarterFact]]:
        try:
            facts = await sec.companyfacts(row["cik"])
        except Exception:
            stats.errors += 1
            return []
        if not facts:
            return []
        candidates: list[tuple[dict, QuarterFact]] = []
        for field in fields:
            for fact in quarterly_facts(facts, field)[:quarters_back]:
                candidates.append((row, fact))
        if not candidates:
            return []
        perm = shuffle_indices(len(candidates), seed ^ row["cik"])
        return [candidates[i] for i in perm[:per_company]]

    per_company_lists = await bounded_gather(
        seed_rows, company_facts, concurrency=COMPANY_CONCURRENCY
    )

    rows: list[dict[str, Any]] = []
    syntax_idx = 0
    for company_list in per_company_lists:
        if not company_list:
            stats.facts_missing += 1
        for row, fact in company_list:
            syntax = FILINGS_SYNTAX_CYCLE[syntax_idx % len(FILINGS_SYNTAX_CYCLE)]
            syntax_idx += 1
            rows.append(
                build_filing_row(
                    company=row["title"],
                    ticker=row["ticker"],
                    cik=row["cik"],
                    tier=row.get("tier") or "",
                    fact=fact,
                    query_text=filings_query(row["title"], fact, syntax),
                    syntax=syntax,
                    hour_ts=hour_ts,
                    now=now,
                )
            )
    stats.filings_rows = len(rows)
    return rows


async def _filingdoc_rows(
    seed_rows: list[dict],
    edgar: EdgarClient,
    llm: LLMClient,
    *,
    target: int,
    seed: int,
    hour_ts: datetime,
    doc_concurrency: int,
    stats: GenStats,
) -> list[dict[str, Any]]:
    perm = shuffle_indices(len(seed_rows), seed ^ 0xF111)
    companies = [seed_rows[i] for i in perm[: target * DOC_OVERSAMPLE]]
    stats.doc_candidates = len(companies)

    async def project(row: dict) -> tuple[Filing, str] | str:
        filings = await edgar.filings(row["cik"], forms=DOC_FORMS, limit=20)
        if not filings:
            return "fetch"
        pick = filings[(seed ^ row["cik"]) % len(filings)]
        filing = Filing(
            cik=row["cik"],
            company=row["title"],
            ticker=row["ticker"],
            form=pick["form"],
            adsh=pick["adsh"],
            filed=pick["filed"],
            primary_doc=pick["primary_doc"],
            tier=row.get("tier") or "",
        )
        text = await edgar.document_text(filing)
        if not text:
            return "fetch"
        if len(text) < MIN_DOC_CHARS:
            return "thin"
        try:
            reply, err = await llm.complete(
                build_filingdoc_prompt(filing, text), max_tokens=256, reasoning_effort="minimal"
            )
        except Exception:
            return "llm_error"
        if err is not None:
            return "llm_error"
        query = clean_filingdoc_query(reply)
        if query is None:
            return "no_query"
        if not filingdoc_query_ok(query, filing=filing, text=text):
            return "rejected"
        return filing, query

    projected = await bounded_gather(companies, project, concurrency=doc_concurrency)

    drop_stat = {
        "fetch": "doc_fetch_fail",
        "thin": "doc_thin",
        "llm_error": "llm_errors",
        "no_query": "doc_no_query",
        "rejected": "doc_rejected",
    }
    rows: list[dict[str, Any]] = []
    syntax_idx = 0
    for outcome in projected:
        if isinstance(outcome, str):
            setattr(stats, drop_stat[outcome], getattr(stats, drop_stat[outcome]) + 1)
            continue
        if len(rows) >= target:
            continue
        filing, query = outcome
        syntax = FILINGDOC_SYNTAX_CYCLE[syntax_idx % len(FILINGDOC_SYNTAX_CYCLE)]
        syntax_idx += 1
        rows.append(
            build_filingdoc_row(
                filing,
                query_text=filingdoc_syntax_query(query, syntax, filed=filing.filed),
                syntax=syntax,
                hour_ts=hour_ts,
            )
        )
    stats.filingdoc_rows = len(rows)
    return rows


async def run_generate(
    *,
    sec: SecClient | None,
    edgar: EdgarClient | None,
    llm: LLMClient | None,
    seed_rows: list[dict],
    hour_ts: datetime,
    now: datetime,
    fields: tuple[str, ...],
    per_company: int,
    quarters_back: int,
    filingdoc_target: int,
    seed: int,
    doc_concurrency: int = 8,
) -> tuple[list[dict[str, Any]], GenStats]:
    stats = GenStats()
    stats.companies = len(seed_rows)
    rows: list[dict[str, Any]] = []
    if sec is not None:
        rows.extend(
            await _filings_rows(
                seed_rows,
                sec,
                fields=fields,
                per_company=per_company,
                quarters_back=quarters_back,
                seed=seed,
                hour_ts=hour_ts,
                now=now,
                stats=stats,
            )
        )
    if edgar is not None and llm is not None:
        rows.extend(
            await _filingdoc_rows(
                seed_rows,
                edgar,
                llm,
                target=filingdoc_target,
                seed=seed,
                hour_ts=hour_ts,
                doc_concurrency=doc_concurrency,
                stats=stats,
            )
        )
    seen_ids: set[str] = set()
    unique_rows = []
    for row in rows:
        if row["query_id"] in seen_ids:
            continue
        seen_ids.add(row["query_id"])
        unique_rows.append(row)
    return unique_rows, stats
