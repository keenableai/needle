import asyncio
import time
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as ET
import httpx


@dataclass(frozen=True)
class SeedSource:
    url: str
    source_kind: str
    topical_domain: str


SEED_SOURCES: tuple[SeedSource, ...] = (
    SeedSource("https://www.local10.com/arc/outboundfeeds/rss/", "rss_news", "local_civic"),
    SeedSource("https://www.seattletimes.com/feed/", "rss_news", "local_civic"),
    SeedSource("https://chicago.suntimes.com/rss/index.xml", "rss_news", "local_civic"),
    SeedSource("https://nypost.com/metro/feed/", "rss_news", "local_civic"),
    SeedSource("https://rss.nytimes.com/services/xml/rss/nyt/NYRegion.xml", "rss_news", "local_civic"),
    SeedSource("https://gothamist.com/feed", "rss_news", "local_civic"),
    SeedSource("https://www.12news.com/feeds/syndication/rss/news/local", "rss_news", "local_civic"),
    SeedSource("https://www.kxan.com/feed/", "rss_news", "local_civic"),
    SeedSource("https://blockclubchicago.org/feed/", "rss_news", "local_civic"),
    SeedSource("https://www.latimes.com/california/rss2.0.xml", "rss_news", "local_civic"),
    SeedSource("https://www.westword.com/feed", "rss_news", "local_civic"),
    SeedSource("https://missionlocal.org/feed/", "rss_news", "local_civic"),
    SeedSource("https://www.cpr.org/feed/", "rss_news", "local_civic"),
    SeedSource("https://www.dallasobserver.com/feed", "rss_news", "local_civic"),
    SeedSource("https://www.nbcmiami.com/news/local/feed/", "rss_news", "local_civic"),
    SeedSource("https://www.thecity.nyc/feed", "rss_news", "local_civic"),
    SeedSource("https://newbostonpost.com/feed/", "rss_news", "local_civic"),
    SeedSource("https://www.texasstandard.org/feed/", "rss_news", "local_civic"),
    SeedSource("https://www.washingtoncitypaper.com/feed/", "rss_news", "local_civic"),
    SeedSource("https://www.universalhub.com/rss.xml", "rss_news", "local_civic"),
    SeedSource("https://www.phoenixnewtimes.com/feed", "rss_news", "local_civic"),
    SeedSource("https://www.miaminewtimes.com/feed", "rss_news", "local_civic"),
    SeedSource("https://www.bostonmagazine.com/feed/", "rss_news", "local_civic"),
    SeedSource("https://sfist.com/feed/", "rss_news", "local_civic"),
    SeedSource("https://www.wbez.org/rss", "rss_news", "local_civic"),
    SeedSource("https://news.wttw.com/feed", "rss_news", "local_civic"),
    SeedSource("https://www.texastribune.org/feed/", "rss_news", "local_civic"),
    SeedSource("https://www.minnpost.com/feed/", "rss_news", "local_civic"),
    SeedSource("https://denverite.com/feed/", "rss_news", "local_civic"),
    SeedSource("https://voiceofsandiego.org/feed/", "rss_news", "local_civic"),
    SeedSource("https://techcrunch.com/feed/", "rss_news", "tech"),
    SeedSource("https://www.theverge.com/rss/index.xml", "rss_news", "tech"),
    SeedSource("https://www.wired.com/feed/rss", "rss_news", "tech"),
    SeedSource("https://www.engadget.com/rss.xml", "rss_news", "tech"),
    SeedSource("https://gizmodo.com/rss", "rss_news", "tech"),
    SeedSource("https://9to5mac.com/feed/", "rss_news", "tech"),
    SeedSource("https://www.androidauthority.com/feed", "rss_news", "tech"),
    SeedSource("https://feeds.macrumors.com/MacRumors-All", "rss_news", "tech"),
    SeedSource("https://appleinsider.com/rss/news/", "rss_news", "tech"),
    SeedSource("https://www.tomshardware.com/feeds/all", "rss_news", "tech"),
    SeedSource("https://www.cnet.com/rss/news/", "rss_news", "tech"),
    SeedSource("https://www.theregister.com/headlines.atom", "rss_news", "tech"),
    SeedSource("https://thenextweb.com/feed/", "rss_news", "tech"),
    SeedSource("http://feeds.mashable.com/Mashable", "rss_news", "tech"),
    SeedSource("https://hnrss.org/frontpage", "rss_social", "tech"),
    SeedSource("https://hnrss.org/best", "rss_social", "tech"),
    SeedSource("https://hnrss.org/show", "rss_social", "tech"),
    SeedSource("https://lobste.rs/rss", "rss_social", "tech"),
    SeedSource("https://dev.to/feed", "rss_social", "tech"),
    SeedSource("https://stackoverflow.com/feeds", "rss_social", "tech"),
    SeedSource(
        "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
        "rss_news",
        "finance",
    ),
    SeedSource("https://finance.yahoo.com/news/rssindex", "rss_news", "finance"),
    SeedSource("https://feeds.content.dowjones.io/public/rss/mw_topstories", "rss_news", "finance"),
    SeedSource("https://seekingalpha.com/feed.xml", "rss_news", "finance"),
    SeedSource("https://www.thestreet.com/.rss/full/", "rss_news", "finance"),
    SeedSource("https://www.forbes.com/business/feed/", "rss_news", "finance"),
    SeedSource("https://fortune.com/feed", "rss_news", "finance"),
    SeedSource("https://www.inc.com/rss/", "rss_news", "finance"),
    SeedSource("https://www.nerdwallet.com/blog/feed/", "rss_news", "finance"),
    SeedSource("https://www.investing.com/rss/news.rss", "rss_news", "finance"),
    SeedSource("https://variety.com/feed/", "rss_news", "entertainment"),
    SeedSource("https://www.hollywoodreporter.com/feed/", "rss_news", "entertainment"),
    SeedSource("https://deadline.com/feed/", "rss_news", "entertainment"),
    SeedSource("https://www.thewrap.com/feed/", "rss_news", "entertainment"),
    SeedSource("https://screenrant.com/feed/", "rss_news", "entertainment"),
    SeedSource("https://collider.com/feed/", "rss_news", "entertainment"),
    SeedSource("https://decider.com/feed/", "rss_news", "entertainment"),
    SeedSource("https://pitchfork.com/rss/news/", "rss_news", "entertainment"),
    SeedSource("https://www.rollingstone.com/feed/", "rss_news", "entertainment"),
    SeedSource("http://consequenceofsound.net/feed", "rss_news", "entertainment"),
    SeedSource("https://www.comingsoon.net/feed", "rss_news", "entertainment"),
    SeedSource("https://tvline.com/feed/", "rss_news", "entertainment"),
    SeedSource("https://www.indiewire.com/feed", "rss_news", "entertainment"),
    SeedSource("https://sports.yahoo.com/rss/", "rss_news", "sports"),
    SeedSource("https://www.espn.com/espn/rss/news", "rss_news", "sports"),
    SeedSource("https://profootballtalk.nbcsports.com/feed/", "rss_news", "sports"),
    SeedSource("https://www.espn.com/espn/rss/nfl/news", "rss_news", "sports"),
    SeedSource("https://www.espn.com/espn/rss/nba/news", "rss_news", "sports"),
    SeedSource("https://www.espn.com/espn/rss/mlb/news", "rss_news", "sports"),
    SeedSource("https://www.cbssports.com/rss/headlines/nba/", "rss_news", "sports"),
    SeedSource("https://www.cbssports.com/rss/headlines/nfl/", "rss_news", "sports"),
    SeedSource("https://defector.com/feed", "rss_news", "sports"),
    SeedSource("https://www.sbnation.com/rss/index.xml", "rss_news", "sports"),
    SeedSource("https://www.polygon.com/rss/index.xml", "rss_news", "gaming"),
    SeedSource("https://www.eurogamer.net/feed", "rss_news", "gaming"),
    SeedSource("https://feeds.ign.com/ign/games-all", "rss_news", "gaming"),
    SeedSource("https://www.pcgamer.com/rss/", "rss_news", "gaming"),
    SeedSource("https://kotaku.com/rss", "rss_news", "gaming"),
    SeedSource("https://www.gamespot.com/feeds/mashup/", "rss_news", "gaming"),
    SeedSource("https://www.destructoid.com/feed/", "rss_news", "gaming"),
    SeedSource("https://www.rockpapershotgun.com/feed/news", "rss_news", "gaming"),
    SeedSource("https://www.statnews.com/feed/", "rss_news", "health"),
    SeedSource("https://feeds.npr.org/1128/rss.xml", "rss_news", "health"),
    SeedSource("https://www.medpagetoday.com/rss/headlines.xml", "rss_news", "health"),
    SeedSource("https://www.endpts.com/feed/", "rss_news", "health"),
    SeedSource("https://kffhealthnews.org/feed/", "rss_news", "health"),
    SeedSource("https://phys.org/rss-feed/", "rss_news", "science"),
    SeedSource("https://www.space.com/feeds/all", "rss_news", "science"),
    SeedSource("https://scitechdaily.com/feed/", "rss_news", "science"),
    SeedSource("https://rss.nytimes.com/services/xml/rss/nyt/Science.xml", "rss_news", "science"),
    SeedSource("https://www.nasa.gov/news-release/feed/", "rss_news", "science"),
    SeedSource("https://www.livescience.com/feeds/all", "rss_news", "science"),
    SeedSource("https://export.arxiv.org/rss/cs.IR", "rss_paper", "science"),
    SeedSource("https://export.arxiv.org/rss/cs.CL", "rss_paper", "science"),
    SeedSource("https://export.arxiv.org/rss/cs.LG", "rss_paper", "science"),
    SeedSource("https://feeds.npr.org/1014/rss.xml", "rss_news", "government"),
    SeedSource("https://thehill.com/news/feed/", "rss_news", "government"),
    SeedSource("https://www.producthunt.com/feed", "rss_release", "commerce"),
    SeedSource("https://www.howtogeek.com/feed/", "rss_news", "commerce"),
    SeedSource("https://www.makeuseof.com/feed/", "rss_news", "commerce"),
    SeedSource("https://www.gearpatrol.com/feed/", "rss_news", "commerce"),
    SeedSource("https://petapixel.com/feed/", "rss_news", "commerce"),
    SeedSource("https://www.thekitchn.com/main.rss", "rss_news", "commerce"),
    SeedSource("https://www.nytimes.com/wirecutter/feed/", "rss_news", "commerce"),
    SeedSource("https://www.caranddriver.com/rss/all.xml", "rss_news", "automotive"),
    SeedSource("https://electrek.co/feed/", "rss_news", "automotive"),
    SeedSource("https://jalopnik.com/rss", "rss_news", "automotive"),
    SeedSource("https://www.the74million.org/feed/", "rss_news", "education"),
    SeedSource("https://www.insidehighered.com/rss.xml", "rss_news", "education"),
    SeedSource("https://www.k12dive.com/feeds/news/", "rss_news", "education"),
    SeedSource("https://onemileatatime.com/feed/", "rss_news", "travel"),
    SeedSource("https://www.cntraveler.com/feed/rss", "rss_news", "travel"),
    SeedSource("https://skift.com/feed/", "rss_news", "travel"),
    SeedSource("https://viewfromthewing.com/feed/", "rss_news", "travel"),
)


HTTP_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
USER_AGENT = "keenbench-freshstream/0.1 (+https://github.com/keenable/keenbench)"

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}

RAW_MAX_AGE_DEFAULT = timedelta(hours=6)
RAW_MAX_AGE_BY_KIND: dict[str, timedelta] = {"rss_paper": timedelta(hours=168)}

QUERY_MAX_AGE_DEFAULT = timedelta(hours=1)
QUERY_MAX_AGE_BY_KIND: dict[str, timedelta] = {"rss_paper": timedelta(hours=168)}

HEALTH_WINDOWS: tuple[tuple[str, timedelta], ...] = (
    ("items_lt_1h", timedelta(hours=1)),
    ("items_lt_6h", timedelta(hours=6)),
    ("items_lt_24h", timedelta(hours=24)),
    ("items_lt_48h", timedelta(hours=48)),
)

RSS_KINDS: frozenset[str] = frozenset(
    {"rss_news", "rss_release", "rss_blog", "rss_paper", "rss_social"}
)


def load_sources_from_toml(path: str | Path) -> tuple[SeedSource, ...]:
    data = tomllib.loads(Path(path).read_text())
    return tuple(
        SeedSource(
            url=s["url"], source_kind=s["source_kind"], topical_domain=s["topical_domain"]
        )
        for s in data.get("source", [])
    )


@dataclass(frozen=True)
class _FetchOutcome:
    text: str | None
    http_status: int
    fetch_error_class: str | None


def _classify_httpx_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connection"
    name = type(exc).__name__.lower()
    if "ssl" in name:
        return "ssl"
    if isinstance(exc, httpx.InvalidURL):
        return "invalid_url"
    if isinstance(exc, httpx.TooManyRedirects):
        return "too_many_redirects"
    return "other"


async def _fetch_text(client: httpx.AsyncClient, url: str) -> _FetchOutcome:
    try:
        r = await client.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        return _FetchOutcome(text=None, http_status=-1, fetch_error_class=_classify_httpx_error(exc))
    if r.status_code != 200:
        return _FetchOutcome(text=None, http_status=r.status_code, fetch_error_class="http_error")
    return _FetchOutcome(text=r.text, http_status=200, fetch_error_class=None)


def _text_of(el: Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    return el.text.strip() or None


def _parse_feed(root: Element) -> list[dict[str, str | None]]:
    entries: list[dict[str, str | None]] = []

    for item in root.findall(".//item"):
        entries.append(
            {
                "title": _text_of(item.find("title")),
                "summary": _text_of(item.find("description")),
                "url": _text_of(item.find("link")),
                "published_at": _text_of(item.find("pubDate")) or _text_of(item.find("dc:date", NS)),
            }
        )

    for entry in root.findall("atom:entry", NS):
        link_el = entry.find("atom:link", NS)
        link = link_el.get("href") if link_el is not None else None
        entries.append(
            {
                "title": _text_of(entry.find("atom:title", NS)),
                "summary": _text_of(entry.find("atom:summary", NS))
                or _text_of(entry.find("atom:content", NS)),
                "url": link,
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


def _raw_max_age_for_kind(source_kind: str) -> timedelta:
    return RAW_MAX_AGE_BY_KIND.get(source_kind, RAW_MAX_AGE_DEFAULT)


def _query_max_age_for_kind(source_kind: str) -> timedelta:
    return QUERY_MAX_AGE_BY_KIND.get(source_kind, QUERY_MAX_AGE_DEFAULT)


async def _fetch_one(
    client: httpx.AsyncClient,
    source: SeedSource,
    *,
    max_rows_per_source: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.perf_counter()
    outcome = await _fetch_text(client, source.url)
    fetch_duration_ms = (time.perf_counter() - started) * 1000.0
    now = datetime.now(UTC)

    base_health: dict[str, Any] = {
        "source_url": source.url,
        "source_kind": source.source_kind,
        "topical_domain": source.topical_domain,
        "http_status": outcome.http_status,
        "fetch_error_class": outcome.fetch_error_class,
        "parse_ok": False,
        "items_total": 0,
        "items_lt_1h": 0,
        "items_lt_6h": 0,
        "items_lt_24h": 0,
        "items_lt_48h": 0,
        "newest_item_age_minutes": None,
        "fetch_duration_ms": fetch_duration_ms,
        "observed_at": now,
    }

    if outcome.text is None:
        return [], base_health

    try:
        root = ET.fromstring(outcome.text)
    except ET.ParseError:
        return [], base_health
    base_health["parse_ok"] = True

    parsed_items = _parse_feed(root)
    base_health["items_total"] = len(parsed_items)

    max_age_seconds = _raw_max_age_for_kind(source.source_kind).total_seconds()
    item_ages_seconds: list[float] = []
    recent_items: list[dict[str, str | None]] = []
    newest_age_seconds: float | None = None
    for e in parsed_items:
        dt = parse_published_date(e.get("published_at"))
        if dt is None:
            recent_items.append(e)
            continue
        age = (now - dt).total_seconds()
        if age < 0:
            continue
        item_ages_seconds.append(age)
        if newest_age_seconds is None or age < newest_age_seconds:
            newest_age_seconds = age
        if age <= max_age_seconds:
            recent_items.append(e)

    for col, window in HEALTH_WINDOWS:
        window_seconds = window.total_seconds()
        base_health[col] = sum(1 for s in item_ages_seconds if s <= window_seconds)
    if newest_age_seconds is not None:
        base_health["newest_item_age_minutes"] = newest_age_seconds / 60.0

    entries = recent_items[:max_rows_per_source]
    item_rows = [
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
        for e in entries
    ]
    return item_rows, base_health


async def fetch_all_sources(
    sources: tuple[SeedSource, ...],
    *,
    max_rows_per_source: int = 50,
    concurrency: int = 15,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:

        async def _one(s: SeedSource) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            async with sem:
                return await _fetch_one(client, s, max_rows_per_source=max_rows_per_source)

        results = await asyncio.gather(*[_one(s) for s in sources])

    items: list[dict[str, Any]] = []
    healths: list[dict[str, Any]] = []
    for item_rows, health_row in results:
        items.extend(item_rows)
        healths.append(health_row)
    return items, healths


def pick_per_feed(items: list[dict[str, Any]], *, now: datetime) -> list[dict[str, Any]]:
    by_feed: dict[str, tuple[float, dict[str, Any]]] = {}
    for r in items:
        source_kind = str(r.get("source_kind") or "")
        if source_kind not in RSS_KINDS:
            continue
        dt = parse_published_date(r.get("lastmod_or_pub_at"))
        if dt is None:
            continue
        age = (now - dt).total_seconds()
        if age < 0 or age > _query_max_age_for_kind(source_kind).total_seconds():
            continue
        parent = str(r.get("parent_site") or "")
        prev = by_feed.get(parent)
        if prev is None or age < prev[0]:
            by_feed[parent] = (age, r)
    return [r for _, r in by_feed.values()]
