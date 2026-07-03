from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from keenbench.scholar.models import Paper, build_gold_row
from keenbench.scholar.projection import (
    body_query_ok,
    build_body_prompt,
    clean_body_query,
    degrade_title,
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

# Narrow bands at each bucket's target age so a paper's true published-date age
# lands inside the bucket; a wide window + newest-first source ordering would
# pile every result at the young edge and mislabel it.
AGE_BANDS = {
    "7d": (7, 0),
    "30d": (30, 23),
    "1y": (364, 357),
    "older": (740, 726),
}


@dataclass
class GenStats:
    candidates: int = 0
    papers: int = 0
    title_rows: int = 0
    body_rows: int = 0
    body_fetch_fail: int = 0
    body_no_query: int = 0
    body_leak_rejected: int = 0
    llm_errors: int = 0
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
    candidates: list[tuple[tuple[str, str], Paper]] = []
    for cell, papers in zip(cells, candidate_lists, strict=True):
        for paper in papers:
            if not degrade_title(paper.title) or paper.paper_key in seen_keys:
                continue
            seen_keys.add(paper.paper_key)
            candidates.append((cell, replace(paper, domain=cell[0])))
    stats.candidates = len(candidates)

    async def _pair(
        item: tuple[tuple[str, str], Paper],
    ) -> tuple[tuple[str, str], Paper, str | None]:
        _, paper = item
        body = await _fetch_body(paper, arxiv=arxiv, europepmc=europepmc)
        if not body:
            return item[0], paper, None
        query, err = await _body_query(llm, paper, body)
        if err is not None:
            return item[0], paper, "__llm_error__"
        if query is None:
            return item[0], paper, "__no_query__"
        if not body_query_ok(query, title=paper.title, abstract=paper.abstract):
            return item[0], paper, "__leak__"
        return item[0], paper, query

    paired = await bounded_gather(candidates, _pair, concurrency=body_concurrency)

    by_cell: dict[tuple[str, str], list[tuple[Paper, str]]] = {c: [] for c in cells}
    for cell, paper, body_query in paired:
        if body_query is None:
            stats.body_fetch_fail += 1
        elif body_query == "__llm_error__":
            stats.llm_errors += 1
        elif body_query == "__no_query__":
            stats.body_no_query += 1
        elif body_query == "__leak__":
            stats.body_leak_rejected += 1
        else:
            by_cell[cell].append((paper, body_query))

    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for cell in cells:
        selected = by_cell[cell][:per_cell]
        if len(selected) < per_cell:
            stats.short_cells += 1
        for paper, body_query in selected:
            title_query = degrade_title(paper.title)
            if not title_query:
                continue
            for bucket, text in (("title", title_query), ("body", body_query)):
                row = build_gold_row(
                    paper, query_text=text, bucket=bucket, hour_ts=hour_ts, now=now
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
