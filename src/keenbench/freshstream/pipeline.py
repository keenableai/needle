from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from keenbench.freshstream.feeds import SeedSource, fetch_all_sources, pick_per_feed
from keenbench.freshstream.models import QueryRow, build_query_row
from keenbench.freshstream.projection import (
    build_projection_prompt,
    build_trend_prompt,
    project_batch,
)
from keenbench.freshstream.taxonomy import TOPICAL_DOMAINS
from keenbench.freshstream.trends import TrendsProvider
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


def _fetch_anchor(items: list[dict[str, Any]]) -> datetime:
    times = [i["observed_at"] for i in items if i.get("observed_at")]
    return max(times) if times else datetime.now(UTC)


def _rss_provenance(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "producer": "rss_queries",
        "source_kind": record.get("source_kind"),
        "parent_site": record.get("parent_site"),
        "url": record.get("url"),
        "title": record.get("title"),
        "lastmod_or_pub_at": record.get("lastmod_or_pub_at"),
    }


def _rss_row_meta(record: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    td = str(record.get("topical_domain_default") or "other")
    if td not in TOPICAL_DOMAINS:
        td = "other"
    return td, _rss_provenance(record)


def _collect_rows(
    projections: list[tuple[Any, str | None, dict[str, str] | None]],
    *,
    hour_ts: datetime,
    bucket: str,
    row_meta: Callable[[Any], tuple[str, dict[str, Any]]],
) -> tuple[list[QueryRow], int, int, int]:
    rows: list[QueryRow] = []
    seen_ids: set[str] = set()
    llm_errors = no_news_event = duplicates = 0
    for item, query_text, err in projections:
        if err is not None:
            llm_errors += 1
            continue
        if not query_text:
            no_news_event += 1
            continue
        topical_domain, provenance = row_meta(item)
        row = build_query_row(
            query_text=query_text,
            hour_ts=hour_ts,
            bucket=bucket,
            topical_domain=topical_domain,
            provenance=provenance,
        )
        if row.query_id in seen_ids:
            duplicates += 1
            continue
        seen_ids.add(row.query_id)
        rows.append(row)
    return rows, llm_errors, no_news_event, duplicates


def _trend_provenance(trend: Any) -> dict[str, Any]:
    return {
        "producer": "trends_queries",
        "topic": trend.topic,
        "approx_traffic": trend.approx_traffic,
        "news_items": [
            {"title": n.title, "url": n.url, "source": n.source} for n in trend.news_items[:5]
        ],
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
    items, health = await fetch_all_sources(
        sources, max_rows_per_source=max_rows_per_source, concurrency=fetch_concurrency
    )
    anchor = now if now is not None else _fetch_anchor(items)
    candidates = pick_per_feed(items, now=anchor)
    today = hour_ts.strftime("%Y-%m-%d")
    projections = await project_batch(
        llm,
        candidates,
        lambda r: build_projection_prompt(r, today=today),
        concurrency=llm_concurrency,
    )
    rows, llm_errors, no_news_event, duplicates = _collect_rows(
        projections, hour_ts=hour_ts, bucket="rss", row_meta=_rss_row_meta
    )
    return rows, RunStats(
        feeds=len(sources),
        candidates=len(candidates),
        projected=len(rows),
        no_news_event=no_news_event,
        llm_errors=llm_errors,
        duplicates=duplicates,
        feed_health=health,
    )


async def run_trends(
    provider: TrendsProvider,
    llm: LLMClient,
    *,
    hour_ts: datetime,
    max_trends: int = 0,
    llm_concurrency: int = 8,
) -> tuple[list[QueryRow], RunStats]:
    trends = await provider.fetch()
    if max_trends > 0:
        trends = trends[:max_trends]
    today = hour_ts.strftime("%Y-%m-%d")
    projections = await project_batch(
        llm, trends, lambda t: build_trend_prompt(t, today=today), concurrency=llm_concurrency
    )
    rows, llm_errors, no_news_event, duplicates = _collect_rows(
        projections,
        hour_ts=hour_ts,
        bucket="trending",
        row_meta=lambda t: ("other", _trend_provenance(t)),
    )
    return rows, RunStats(
        candidates=len(trends),
        projected=len(rows),
        no_news_event=no_news_event,
        llm_errors=llm_errors,
        duplicates=duplicates,
    )
