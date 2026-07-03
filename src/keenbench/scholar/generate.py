from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from keenbench.scholar.models import AGE_BANDS, Paper, build_gold_row
from keenbench.scholar.projection import (
    body_has_bad_anchor,
    body_query_ok,
    build_body_prompt,
    clean_body_query,
    degrade_title,
    title_is_specific,
)
from keenbench.scholar.sources import ArxivClient, EuropePmcClient
from keenbench.shared.concurrency import bounded_gather
from keenbench.shared.llm import LLMClient

ARXIV_DOMAINS = (
    "computer science",
    "physical sciences",
    "life sciences",
    "social sciences",
)
HEALTH_DOMAIN = "health sciences"
OVERSAMPLE = 3

_DROP_STAT = {
    "fetch": "body_fetch_fail",
    "llm_error": "llm_errors",
    "no_query": "body_no_query",
    "bad_anchor": "body_bad_anchor",
    "leak": "body_leak_rejected",
}


@dataclass(frozen=True)
class Candidate:
    cell: tuple[str, str]
    paper: Paper
    title_query: str


@dataclass
class GenStats:
    candidates: int = 0
    papers: int = 0
    title_rows: int = 0
    body_rows: int = 0
    body_fetch_fail: int = 0
    body_no_query: int = 0
    body_bad_anchor: int = 0
    body_leak_rejected: int = 0
    llm_errors: int = 0
    generic_title: int = 0
    short_cells: int = 0


def _bucket_window(bucket: str, *, now: datetime) -> tuple[str, str]:
    start_days, end_days = AGE_BANDS[bucket]
    start = now - timedelta(days=start_days)
    end = now - timedelta(days=end_days)
    return start.date().isoformat(), end.date().isoformat()


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
    from_date, to_date = _bucket_window(bucket, now=now)
    if domain == HEALTH_DOMAIN:
        if europepmc is None:
            return []
        return await europepmc.recent(from_date=from_date, to_date=to_date, n=n, seed=seed)
    if arxiv is None:
        return []
    return await arxiv.search_domain(domain, from_date=from_date, to_date=to_date, max_results=n)


async def _fetch_body(
    paper: Paper, *, arxiv: ArxivClient | None, europepmc: EuropePmcClient | None
) -> str | None:
    if paper.suite == "arxiv" and arxiv is not None and paper.arxiv_id:
        return await arxiv.body(paper.arxiv_id)
    if paper.suite == "europepmc" and europepmc is not None and paper.pmcid:
        return await europepmc.body(paper.pmcid)
    return None


async def _body_query(
    llm: LLMClient, paper: Paper, body: str
) -> tuple[str | None, dict[str, str] | None]:
    try:
        text, err = await llm.complete(
            build_body_prompt(paper, body), max_tokens=256, reasoning_effort="minimal"
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
    llm: LLMClient,
    hour_ts: datetime,
    now: datetime,
    age_buckets: tuple[str, ...],
    per_cell: int,
    seed: int,
    body_concurrency: int = 8,
) -> tuple[list[dict[str, Any]], GenStats]:
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

    async def _pair(cand: Candidate) -> tuple[Candidate, str | None, str | None]:
        body = await _fetch_body(cand.paper, arxiv=arxiv, europepmc=europepmc)
        if not body:
            return cand, None, "fetch"
        query, err = await _body_query(llm, cand.paper, body)
        if err is not None:
            return cand, None, "llm_error"
        if query is None:
            return cand, None, "no_query"
        if body_has_bad_anchor(query):
            return cand, None, "bad_anchor"
        if not body_query_ok(query, title=cand.paper.title, abstract=cand.paper.abstract):
            return cand, None, "leak"
        return cand, query, None

    paired = await bounded_gather(candidates, _pair, concurrency=body_concurrency)

    by_cell: dict[tuple[str, str], list[tuple[Candidate, str]]] = {c: [] for c in cells}
    for cand, body_query, drop in paired:
        if drop is not None:
            setattr(stats, _DROP_STAT[drop], getattr(stats, _DROP_STAT[drop]) + 1)
        elif body_query is not None:
            by_cell[cand.cell].append((cand, body_query))

    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for cell in cells:
        selected = by_cell[cell][:per_cell]
        if len(selected) < per_cell:
            stats.short_cells += 1
        for cand, body_query in selected:
            for bucket, text in (("title", cand.title_query), ("body", body_query)):
                row = build_gold_row(
                    cand.paper, query_text=text, bucket=bucket, hour_ts=hour_ts, now=now
                )
                if row["query_id"] in seen_ids:
                    continue
                seen_ids.add(row["query_id"])
                rows.append(row)
                if bucket == "title":
                    stats.title_rows += 1
                else:
                    stats.body_rows += 1
            stats.papers += 1

    return rows, stats
