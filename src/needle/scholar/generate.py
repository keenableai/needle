import asyncio
import random
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from needle.scholar.models import AGE_BANDS, Paper, build_gold_row
from needle.scholar.projection import (
    LLM_BUCKETS,
    body_has_bad_anchor,
    build_query_prompt,
    clean_body_query,
    degrade_title,
    query_ok,
    title_is_specific,
)
from needle.scholar.sources import ArxivClient, EuropePmcClient
from needle.shared.concurrency import bounded_gather
from needle.shared.llm import LLMClient
from needle.shared.retry import MAX_ERROR_CHARS
from needle.shared.sampling import interleave
from needle.shared.search.base import SourceError

ARXIV_DOMAINS = (
    "computer science",
    "physical sciences",
    "life sciences",
    "social sciences",
)
HEALTH_DOMAIN = "health sciences"
QUERY_BUCKETS = ("title",) + LLM_BUCKETS
OVERSAMPLE = 3
MAX_SUBWINDOWS = 24
ARXIV_WINDOW_POOL = 20
ARXIV_MAX_RESULTS = 1000
SOURCE_ABORT_RATE = {"arxiv": 0.2}


@dataclass(frozen=True)
class Candidate:
    cell: tuple[str, str]
    paper: Paper
    title_query: str


@dataclass
class GenStats:
    candidates: int = 0
    papers: int = 0
    rows: dict[str, int] = field(default_factory=dict)
    drops: dict[str, int] = field(default_factory=dict)
    drop_samples: dict[str, str] = field(default_factory=dict)
    generic_title: int = 0
    short_cells: int = 0
    source_requests: Counter[str] = field(default_factory=Counter)
    source_errors: Counter[str] = field(default_factory=Counter)
    source_error_samples: dict[str, str] = field(default_factory=dict)

    def source_summary(self) -> str:
        counts = ", ".join(
            f"{s}={self.source_errors[s]}/{n}" for s, n in sorted(self.source_requests.items())
        )
        return f"source errors: {counts}"

    def check_source(self, suite: str) -> None:
        rate = SOURCE_ABORT_RATE.get(suite)
        if rate is not None and self.source_errors[suite] > rate * self.source_requests[suite]:
            raise SourceError(
                f"{suite} is failing ({self.source_error_samples[suite]}); {self.source_summary()}"
            )


def _suite(domain: str) -> str:
    return "europepmc" if domain == HEALTH_DOMAIN else "arxiv"


def _subwindow_count(bucket: str, n: int) -> int:
    older, newer = AGE_BANDS[bucket]
    span_days = int(older - newer)
    return max(1, min(n, MAX_SUBWINDOWS, span_days))


def _subwindows(bucket: str, *, now: datetime, count: int) -> list[tuple[str, str]]:
    older, newer = AGE_BANDS[bucket]
    edges = [newer + (older - newer) * i / count for i in range(count + 1)]
    windows = []
    for i in range(count):
        from_date = (now - timedelta(days=edges[i + 1])).date().isoformat()
        to_date = (now - timedelta(days=edges[i])).date().isoformat()
        windows.append((from_date, to_date))
    return windows


async def _window_papers(
    domain: str,
    *,
    arxiv: ArxivClient | None,
    europepmc: EuropePmcClient | None,
    from_date: str,
    to_date: str,
    per: int,
    seed: int,
) -> list[Paper]:
    if domain == HEALTH_DOMAIN:
        assert europepmc is not None
        return await europepmc.recent(from_date=from_date, to_date=to_date, n=per, seed=seed)
    assert arxiv is not None
    papers = await arxiv.search_domain(
        domain,
        from_date=from_date,
        to_date=to_date,
        max_results=min(per * ARXIV_WINDOW_POOL, ARXIV_MAX_RESULTS),
    )
    if len(papers) > per:
        papers = random.Random(seed).sample(papers, per)
    return papers


async def _cell_candidates(
    domain: str,
    windows: list[tuple[str, str]],
    *,
    arxiv: ArxivClient | None,
    europepmc: EuropePmcClient | None,
    n: int,
    seed: int,
    stats: GenStats,
) -> list[Paper]:
    per = max(1, -(-n // len(windows)))
    suite = _suite(domain)
    lists: list[list[Paper]] = []
    for wi, (from_date, to_date) in enumerate(windows):
        stats.check_source(suite)
        try:
            papers = await _window_papers(
                domain,
                arxiv=arxiv,
                europepmc=europepmc,
                from_date=from_date,
                to_date=to_date,
                per=per,
                seed=seed + wi,
            )
        except SourceError as exc:
            stats.source_errors[suite] += 1
            sample = " ".join(str(exc).split())[:MAX_ERROR_CHARS]
            stats.source_error_samples.setdefault(suite, sample)
            stats.check_source(suite)
            continue
        lists.append(papers)
    return interleave(lists)


async def _fetch_body(
    paper: Paper, *, arxiv: ArxivClient | None, europepmc: EuropePmcClient | None
) -> str | None:
    if paper.suite == "arxiv" and arxiv is not None and paper.arxiv_id:
        return await arxiv.body(paper.arxiv_id)
    if paper.suite == "europepmc" and europepmc is not None and paper.pmcid:
        return await europepmc.body(paper.pmcid)
    return None


async def _bucket_query(
    llm: LLMClient, bucket: str, paper: Paper, body: str
) -> tuple[str | None, dict[str, str] | None]:
    try:
        text, err = await llm.complete(
            build_query_prompt(bucket, paper, body), max_tokens=1024, reasoning_effort="minimal"
        )
    except Exception as exc:
        return None, {"error_type": "projection_crash", "error_message": str(exc)[:500]}
    if err is not None:
        return None, err
    return clean_body_query(text), None


async def run_generate(
    *,
    arxiv: ArxivClient | None,
    europepmc: EuropePmcClient | None,
    llm: LLMClient | None,
    hour_ts: datetime,
    now: datetime,
    age_buckets: tuple[str, ...],
    per_cell: int,
    seed: int,
    buckets: tuple[str, ...] = QUERY_BUCKETS,
    body_concurrency: int = 8,
) -> tuple[list[dict[str, Any]], GenStats]:
    llm_buckets = tuple(b for b in LLM_BUCKETS if b in buckets)
    if llm_buckets and llm is None:
        raise ValueError(f"llm is required for buckets: {', '.join(llm_buckets)}")
    domains = [d for d in ARXIV_DOMAINS if arxiv is not None]
    if europepmc is not None:
        domains.append(HEALTH_DOMAIN)
    cells = [(d, a) for d in domains for a in age_buckets]
    n = per_cell * OVERSAMPLE
    cell_windows = [_subwindows(a, now=now, count=_subwindow_count(a, n)) for _, a in cells]

    stats = GenStats()
    for (domain, _), windows in zip(cells, cell_windows, strict=True):
        stats.source_requests[_suite(domain)] += len(windows)
    candidate_lists = await bounded_gather(
        list(zip(cells, cell_windows, strict=True)),
        lambda item: _cell_candidates(
            item[0][0],
            item[1],
            arxiv=arxiv,
            europepmc=europepmc,
            n=n,
            seed=seed,
            stats=stats,
        ),
        concurrency=4,
    )
    seen_keys: set[str] = set()
    candidates: list[Candidate] = []
    for cell, papers in zip(cells, candidate_lists, strict=True):
        for paper in papers:
            if paper.paper_key in seen_keys:
                continue
            title_query = degrade_title(paper.title)
            if not title_query or not paper.ids:
                continue
            seen_keys.add(paper.paper_key)
            if not title_is_specific(paper.title):
                stats.generic_title += 1
                continue
            candidates.append(Candidate(cell, replace(paper, domain=cell[0]), title_query))
    stats.candidates = len(candidates)

    async def _pair(
        cand: Candidate,
    ) -> tuple[Candidate, dict[str, str] | None, str | tuple[str, str] | None]:
        if not llm_buckets or llm is None:
            return cand, {}, None
        body = await _fetch_body(cand.paper, arxiv=arxiv, europepmc=europepmc)
        if not body:
            return cand, None, "fetch"
        outs = await asyncio.gather(*[_bucket_query(llm, b, cand.paper, body) for b in llm_buckets])
        queries: dict[str, str] = {}
        for bucket, (query, err) in zip(llm_buckets, outs, strict=True):
            if err is not None:
                sample = f"{err.get('error_type')}: {err.get('error_message')}"[:200]
                return cand, None, (f"{bucket}_llm_error", sample)
            if query is None:
                return cand, None, f"{bucket}_no_query"
            if body_has_bad_anchor(query):
                return cand, None, f"{bucket}_bad_anchor"
            if not query_ok(bucket, query, title=cand.paper.title, abstract=cand.paper.abstract):
                return cand, None, f"{bucket}_leak"
            queries[bucket] = query
        return cand, queries, None

    paired = await bounded_gather(candidates, _pair, concurrency=body_concurrency)

    by_cell: dict[tuple[str, str], list[tuple[Candidate, dict[str, str]]]] = {c: [] for c in cells}
    for cand, queries, drop in paired:
        if drop is not None:
            key, sample = drop if isinstance(drop, tuple) else (drop, None)
            stats.drops[key] = stats.drops.get(key, 0) + 1
            if sample and key not in stats.drop_samples:
                stats.drop_samples[key] = sample
        elif queries is not None:
            by_cell[cand.cell].append((cand, queries))

    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for cell in cells:
        selected = by_cell[cell][:per_cell]
        if len(selected) < per_cell:
            stats.short_cells += 1
        for cand, queries in selected:
            texts = {"title": cand.title_query, **queries}
            for bucket in buckets:
                row = build_gold_row(
                    cand.paper, query_text=texts[bucket], bucket=bucket, hour_ts=hour_ts, now=now
                )
                if row["query_id"] in seen_ids:
                    continue
                seen_ids.add(row["query_id"])
                rows.append(row)
                stats.rows[bucket] = stats.rows.get(bucket, 0) + 1
            stats.papers += 1

    return rows, stats
