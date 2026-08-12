import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from importlib import resources
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, ParseError

import defusedxml.ElementTree as ET
import httpx
from defusedxml.common import DefusedXmlException

from keenbench.shared.concurrency import bounded_gather

DEFAULT_FEEDS_FILE = "feeds.default.toml"


@dataclass(frozen=True)
class SeedSource:
    url: str
    source_kind: str
    topical_domain: str


def _sources_from_data(data: dict[str, Any]) -> tuple[SeedSource, ...]:
    return tuple(
        SeedSource(url=s["url"], source_kind=s["source_kind"], topical_domain=s["topical_domain"])
        for s in data.get("source", [])
    )


def load_sources_from_toml(path: str | Path) -> tuple[SeedSource, ...]:
    return _sources_from_data(tomllib.loads(Path(path).read_text(encoding="utf-8")))


def _load_packaged_default() -> tuple[SeedSource, ...]:
    resource = resources.files(__package__).joinpath("configs", DEFAULT_FEEDS_FILE)
    return _sources_from_data(tomllib.loads(resource.read_text(encoding="utf-8")))


SEED_SOURCES: tuple[SeedSource, ...] = _load_packaged_default()


HTTP_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
USER_AGENT = "keenbench-news/0.1 (+https://github.com/keenableai/keenbench)"

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "rss1": "http://purl.org/rss/1.0/",
}

RAW_MAX_AGE_DEFAULT = timedelta(hours=6)
RAW_MAX_AGE_BY_KIND: dict[str, timedelta] = {"rss_paper": timedelta(hours=168)}

QUERY_MAX_AGE_DEFAULT = timedelta(hours=1)
QUERY_MAX_AGE_BY_KIND: dict[str, timedelta] = {"rss_paper": timedelta(hours=168)}

FUTURE_SKEW_TOLERANCE = timedelta(minutes=5)
FUTURE_SKEW_TOLERANCE_S = FUTURE_SKEW_TOLERANCE.total_seconds()

RSS_KINDS: frozenset[str] = frozenset(
    {"rss_news", "rss_release", "rss_blog", "rss_paper", "rss_social"}
)


async def _fetch_text(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await client.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    except (httpx.HTTPError, httpx.InvalidURL):
        return None
    return r.text if r.status_code == 200 else None


def _text_of(el: Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    return el.text.strip() or None


def _atom_entry_link(entry: Element) -> str | None:
    links = entry.findall("atom:link", NS)
    for el in links:
        if el.get("rel", "alternate") == "alternate":
            return el.get("href")
    return links[0].get("href") if links else None


def _parse_feed(root: Element) -> list[dict[str, str | None]]:
    entries: list[dict[str, str | None]] = []

    for item in root.findall(".//item"):
        entries.append(
            {
                "title": _text_of(item.find("title")),
                "summary": _text_of(item.find("description")),
                "url": _text_of(item.find("link")),
                "published_at": _text_of(item.find("pubDate"))
                or _text_of(item.find("dc:date", NS)),
            }
        )

    for item in root.findall(".//rss1:item", NS):
        entries.append(
            {
                "title": _text_of(item.find("rss1:title", NS)),
                "summary": _text_of(item.find("rss1:description", NS)),
                "url": _text_of(item.find("rss1:link", NS)),
                "published_at": _text_of(item.find("dc:date", NS)),
            }
        )

    for entry in root.findall("atom:entry", NS):
        entries.append(
            {
                "title": _text_of(entry.find("atom:title", NS)),
                "summary": _text_of(entry.find("atom:summary", NS))
                or _text_of(entry.find("atom:content", NS)),
                "url": _atom_entry_link(entry),
                "published_at": _text_of(entry.find("atom:updated", NS))
                or _text_of(entry.find("atom:published", NS)),
            }
        )

    return entries


def parse_published_date(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def published_age_seconds(published_at: str | None, *, now: datetime) -> float | None:
    dt = parse_published_date(published_at)
    if dt is None:
        return None
    age = (now - dt).total_seconds()
    if age < -FUTURE_SKEW_TOLERANCE_S:
        return None
    return max(age, 0.0)


def _raw_max_age_for_kind(source_kind: str) -> timedelta:
    return RAW_MAX_AGE_BY_KIND.get(source_kind, RAW_MAX_AGE_DEFAULT)


def _query_max_age_for_kind(source_kind: str) -> timedelta:
    return QUERY_MAX_AGE_BY_KIND.get(source_kind, QUERY_MAX_AGE_DEFAULT)


async def _fetch_one(
    client: httpx.AsyncClient,
    source: SeedSource,
    *,
    max_rows_per_source: int,
) -> list[dict[str, Any]]:
    text = await _fetch_text(client, source.url)
    now = datetime.now(UTC)
    if text is None:
        return []
    try:
        root = ET.fromstring(text)
    except (ParseError, DefusedXmlException):
        return []

    max_age_seconds = _raw_max_age_for_kind(source.source_kind).total_seconds()
    recent_items: list[dict[str, str | None]] = []
    for e in _parse_feed(root):
        age = published_age_seconds(e.get("published_at"), now=now)
        if age is not None and age <= max_age_seconds:
            recent_items.append(e)

    return [
        {
            "url": e.get("url") or source.url,
            "title": e.get("title"),
            "summary": e.get("summary"),
            "source_kind": source.source_kind,
            "parent_site": source.url,
            "topical_domain_default": source.topical_domain,
            "lastmod_or_pub_at": e.get("published_at"),
            "observed_at": now,
        }
        for e in recent_items[:max_rows_per_source]
    ]


async def fetch_all_sources(
    sources: tuple[SeedSource, ...],
    *,
    max_rows_per_source: int = 50,
    concurrency: int = 15,
) -> list[dict[str, Any]]:
    if max_rows_per_source < 1:
        raise ValueError("max_rows_per_source must be >= 1")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:

        async def _one(s: SeedSource) -> list[dict[str, Any]]:
            return await _fetch_one(client, s, max_rows_per_source=max_rows_per_source)

        results = await bounded_gather(sources, _one, concurrency=concurrency)

    return [row for item_rows in results for row in item_rows]


def pick_per_feed(
    items: list[dict[str, Any]], *, now: datetime, min_candidates: int = 0
) -> list[dict[str, Any]]:
    by_feed: dict[str, tuple[float, dict[str, Any]]] = {}
    for r in items:
        source_kind = str(r.get("source_kind") or "")
        if source_kind not in RSS_KINDS:
            continue
        age = published_age_seconds(r.get("lastmod_or_pub_at"), now=now)
        if age is None:
            continue
        parent = str(r.get("parent_site") or "")
        prev = by_feed.get(parent)
        if prev is None or age < prev[0]:
            by_feed[parent] = (age, r)

    fresh: list[dict[str, Any]] = []
    stale: list[tuple[float, dict[str, Any]]] = []
    for age, r in by_feed.values():
        if age <= _query_max_age_for_kind(str(r["source_kind"])).total_seconds():
            fresh.append(r)
        else:
            stale.append((age, r))
    if len(fresh) < min_candidates:
        stale.sort(key=lambda t: t[0])
        fresh.extend(r for _, r in stale[: min_candidates - len(fresh)])
    return fresh
