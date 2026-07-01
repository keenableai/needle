from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from keenbench.freshstream.feeds import SeedSource, fetch_all_sources, pick_per_feed
from keenbench.freshstream.models import QueryRow, build_query_row
from keenbench.freshstream.projection import project_all
from keenbench.freshstream.taxonomy import TOPICAL_DOMAINS
from keenbench.shared.llm import LLMClient


@dataclass
class RunStats:
    feeds: int = 0
    candidates: int = 0
    projected: int = 0
    no_news_event: int = 0
    llm_errors: int = 0
    duplicates: int = 0
    feed_health: list[dict[str, Any]] = field(default_factory=list)


def _rss_provenance(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "producer": "rss_queries",
        "source_kind": record.get("source_kind"),
        "parent_site": record.get("parent_site"),
        "url": record.get("url"),
        "title": record.get("title"),
        "lastmod_or_pub_at": record.get("lastmod_or_pub_at"),
    }


async def run_rss(
    sources: tuple[SeedSource, ...],
    llm: LLMClient,
    *,
    hour_ts: datetime,
    now: datetime | None = None,
    fetch_concurrency: int = 15,
    llm_concurrency: int = 8,
    max_rows_per_source: int = 50,
) -> tuple[list[QueryRow], RunStats]:
    now = now or datetime.now(UTC)
    items, health = await fetch_all_sources(
        sources, max_rows_per_source=max_rows_per_source, concurrency=fetch_concurrency
    )
    candidates = pick_per_feed(items, now=now)
    projections = await project_all(llm, candidates, concurrency=llm_concurrency)

    rows: list[QueryRow] = []
    seen_ids: set[str] = set()
    stats = RunStats(feeds=len(sources), candidates=len(candidates), feed_health=health)
    for record, query_text, err in projections:
        if err is not None:
            stats.llm_errors += 1
            continue
        if not query_text:
            stats.no_news_event += 1
            continue
        topical_domain = str(record.get("topical_domain_default") or "other")
        if topical_domain not in TOPICAL_DOMAINS:
            topical_domain = "other"
        row = build_query_row(
            query_text=query_text,
            hour_ts=hour_ts,
            bucket="rss",
            topical_domain=topical_domain,
            provenance=_rss_provenance(record),
        )
        if row.query_id in seen_ids:
            stats.duplicates += 1
            continue
        seen_ids.add(row.query_id)
        rows.append(row)

    stats.projected = len(rows)
    return rows, stats
