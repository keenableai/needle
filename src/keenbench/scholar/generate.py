import asyncio
import random
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from keenbench.scholar.models import AGE_BANDS, Paper, build_gold_row
from keenbench.scholar.projection import (
    LLM_BUCKETS,
    body_has_bad_anchor,
    build_query_prompt,
    clean_body_query,
    degrade_title,
    query_ok,
    title_is_specific,
)
from keenbench.scholar.sources import ArxivClient, EuropePmcClient
from keenbench.shared.concurrency import bounded_gather
from keenbench.shared.llm import LLMClient
from keenbench.shared.sampling import interleave

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
    generic_title: int = 0
    short_cells: int = 0


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


async def _cell_candidates(
    domain: str,
    bucket: str,
    *,
    arxiv: ArxivClient | None,
    europepmc: EuropePmcClient | None,
    n: int,
    seed: int,
    now: datetime,
) -> list[Paper]:
    windows = _subwindows(bucket, now=now, count=_subwindow_count(bucket, n))
    per = max(1, -(-n // len(windows)))
    lists: list[list[Paper]] = []
    for wi, (from_date, to_date) in enumerate(windows):
        if domain == HEALTH_DOMAIN:
            if europepmc is not None:
                lists.append(
                    await europepmc.recent(
                        from_date=from_date, to_date=to_date, n=per, seed=seed + wi
                    )
                )
        elif arxiv is not None:
            papers = await arxiv.search_domain(
                domain,
                from_date=from_date,
                to_date=to_date,
                max_results=min(per * ARXIV_WINDOW_POOL, ARXIV_MAX_RESULTS),
            )
            if len(papers) > per:
                papers = random.Random(seed + wi).sample(papers, per)
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
            build_query_prompt(bucket, paper, body), max_tokens=256, reasoning_effort="minimal"
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

    candidate_lists = await bounded_gather(
        cells,
        lambda cell: _cell_candidates(
            cell[0],
            cell[1],
            arxiv=arxiv,
            europepmc=europepmc,
            n=per_cell * OVERSAMPLE,
            seed=seed,
            now=now,
        ),
        concurrency=4,
    )

    stats = GenStats()
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

    async def _pair(cand: Candidate) -> tuple[Candidate, dict[str, str] | None, str | None]:
        if not llm_buckets or llm is None:
            return cand, {}, None
        body = await _fetch_body(cand.paper, arxiv=arxiv, europepmc=europepmc)
        if not body:
            return cand, None, "fetch"
        outs = await asyncio.gather(*[_bucket_query(llm, b, cand.paper, body) for b in llm_buckets])
        queries: dict[str, str] = {}
        for bucket, (query, err) in zip(llm_buckets, outs, strict=True):
            if err is not None:
                return cand, None, f"{bucket}_llm_error"
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
            stats.drops[drop] = stats.drops.get(drop, 0) + 1
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
