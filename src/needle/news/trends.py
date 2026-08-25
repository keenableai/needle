import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol
from xml.etree.ElementTree import ParseError

import defusedxml.ElementTree as ET
import httpx
from defusedxml.common import DefusedXmlException
from rapidfuzz import fuzz

from needle.news.feeds import HTTP_TIMEOUT, _text_of, published_age_seconds
from needle.shared.concurrency import bounded_gather

HT_NS = {"ht": "https://trends.google.com/trending/rss"}
USER_AGENT = "Mozilla/5.0 (compatible; needle-news/0.1)"

US_GEOS: tuple[str, ...] = (
    "US",
    "US-AL",
    "US-AK",
    "US-AZ",
    "US-AR",
    "US-CA",
    "US-CO",
    "US-CT",
    "US-DE",
    "US-DC",
    "US-FL",
    "US-GA",
    "US-HI",
    "US-ID",
    "US-IL",
    "US-IN",
    "US-IA",
    "US-KS",
    "US-KY",
    "US-LA",
    "US-ME",
    "US-MD",
    "US-MA",
    "US-MI",
    "US-MN",
    "US-MS",
    "US-MO",
    "US-MT",
    "US-NE",
    "US-NV",
    "US-NH",
    "US-NJ",
    "US-NM",
    "US-NY",
    "US-NC",
    "US-ND",
    "US-OH",
    "US-OK",
    "US-OR",
    "US-PA",
    "US-RI",
    "US-SC",
    "US-SD",
    "US-TN",
    "US-TX",
    "US-UT",
    "US-VT",
    "US-VA",
    "US-WA",
    "US-WV",
    "US-WI",
    "US-WY",
)

GEO_CONCURRENCY = 10

TRENDS_MAX_AGE = timedelta(hours=24)

DEDUP_THRESHOLD = 90
QUERY_DEDUP_THRESHOLD = 85


def parse_geos(spec: str) -> tuple[str, ...]:
    if spec == "us-all":
        return US_GEOS
    geos = tuple(g.strip() for g in spec.split(",") if g.strip())
    if not geos:
        raise ValueError(f"no geos parsed from {spec!r}")
    return geos


@dataclass(frozen=True)
class NewsItem:
    title: str | None
    url: str | None
    source: str | None


@dataclass(frozen=True)
class Trend:
    topic: str
    approx_traffic: str | None
    pub_date: str | None
    news_items: tuple[NewsItem, ...]
    geos: tuple[str, ...] = ()


class TrendsProvider(Protocol):
    async def fetch(self, geo: str) -> list[Trend]: ...


def approx_traffic_value(s: str | None) -> int:
    if not s:
        return 0
    m = re.match(r"([\d,.]+)\s*([KM]?)", s.strip(), re.IGNORECASE)
    if not m:
        return 0
    try:
        num = float(m.group(1).replace(",", ""))
    except ValueError:
        return 0
    mult = {"K": 1_000, "M": 1_000_000}.get(m.group(2).upper(), 1)
    return int(num * mult)


def parse_trends(xml: str) -> list[Trend]:
    root = ET.fromstring(xml)
    trends: list[Trend] = []
    for item in root.findall(".//item"):
        topic = _text_of(item.find("title"))
        if not topic:
            continue
        news = [
            NewsItem(
                title=_text_of(n.find("ht:news_item_title", HT_NS)),
                url=_text_of(n.find("ht:news_item_url", HT_NS)),
                source=_text_of(n.find("ht:news_item_source", HT_NS)),
            )
            for n in item.findall("ht:news_item", HT_NS)
        ]
        trends.append(
            Trend(
                topic=topic,
                approx_traffic=_text_of(item.find("ht:approx_traffic", HT_NS)),
                pub_date=_text_of(item.find("pubDate")),
                news_items=tuple(news),
            )
        )
    return trends


class GoogleTrendsRssProvider:
    def __init__(
        self,
        *,
        base_url: str = "https://trends.google.com/trending/rss",
        timeout_s: float | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout = httpx.Timeout(timeout_s) if timeout_s else HTTP_TIMEOUT
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch(self, geo: str) -> list[Trend]:
        try:
            resp = await self._http().get(
                self.base_url,
                params={"geo": geo},
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ValueError(
                f"could not fetch Google Trends RSS (geo={geo}): {type(exc).__name__}: {exc}"
            ) from exc
        try:
            return parse_trends(resp.text)
        except (ParseError, DefusedXmlException) as exc:
            raise ValueError(f"could not parse Google Trends RSS (geo={geo}): {exc}") from exc


async def fetch_all_geos(
    provider: TrendsProvider,
    geos: tuple[str, ...],
    *,
    concurrency: int = GEO_CONCURRENCY,
) -> tuple[dict[str, list[Trend]], int]:

    async def _one(geo: str) -> tuple[str, list[Trend] | None]:
        try:
            return geo, await provider.fetch(geo)
        except ValueError:
            return geo, None

    results = await bounded_gather(geos, _one, concurrency=concurrency)
    by_geo = {geo: trends for geo, trends in results if trends is not None}
    return by_geo, len(geos) - len(by_geo)


TOPIC_DEDUP_FLUFF_RE = re.compile(r"\b(vs?|and)\b")

QUERY_DEDUP_FLUFF_RE = re.compile(
    r"\b(vs?|and|match|results?|score|live|today"
    r"|january|february|march|april|may|june|july|august"
    r"|september|october|november|december"
    r"|(?:19|20)\d{2})\b"
)


def _normalize(s: str, fluff_re: re.Pattern[str]) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower()
    s = fluff_re.sub("", s)
    s = re.sub(r"[^a-z0-9\s]", "", s)
    return " ".join(sorted(s.split()))


def collect_unique_trends(trends_by_geo: dict[str, list[Trend]]) -> list[Trend]:
    seen: dict[str, Trend] = {}
    for geo, trends in trends_by_geo.items():
        for trend in trends:
            prev = seen.get(trend.topic)
            if prev is None:
                seen[trend.topic] = replace(trend, geos=(geo,))
            elif geo not in prev.geos:
                seen[trend.topic] = replace(prev, geos=(*prev.geos, geo))
    return list(seen.values())


def dedupe_topics(trends: list[Trend]) -> list[Trend]:
    ordered = sorted(trends, key=lambda t: approx_traffic_value(t.approx_traffic), reverse=True)
    clusters: list[tuple[str, Trend]] = []
    for trend in ordered:
        norm = _normalize(trend.topic, TOPIC_DEDUP_FLUFF_RE)
        merged = False
        for i, (cluster_norm, rep) in enumerate(clusters):
            if fuzz.token_set_ratio(norm, cluster_norm) >= DEDUP_THRESHOLD:
                extra = tuple(g for g in trend.geos if g not in rep.geos)
                if extra:
                    clusters[i] = (cluster_norm, replace(rep, geos=(*rep.geos, *extra)))
                merged = True
                break
        if not merged:
            clusters.append((norm, trend))
    return [rep for _, rep in clusters]


def filter_ascii_topics(trends: list[Trend]) -> list[Trend]:
    return [t for t in trends if t.topic.isascii()]


def cap_by_volume(trends: list[Trend], max_trends: int) -> list[Trend]:
    if max_trends <= 0 or len(trends) <= max_trends:
        return trends
    return sorted(trends, key=lambda t: approx_traffic_value(t.approx_traffic), reverse=True)[
        :max_trends
    ]


def _trend_is_fresh(trend: Trend, *, now: datetime, max_age: timedelta) -> bool:
    age = published_age_seconds(trend.pub_date, now=now)
    return age is not None and age <= max_age.total_seconds()


async def select_trends(
    provider: TrendsProvider,
    geos: tuple[str, ...],
    *,
    now: datetime,
    max_age: timedelta = TRENDS_MAX_AGE,
    max_trends: int = 0,
    concurrency: int = GEO_CONCURRENCY,
) -> tuple[list[Trend], int]:
    trends_by_geo, fetch_errors = await fetch_all_geos(provider, geos, concurrency=concurrency)
    trends = dedupe_topics(collect_unique_trends(trends_by_geo))
    trends = filter_ascii_topics(trends)
    trends = [t for t in trends if _trend_is_fresh(t, now=now, max_age=max_age)]
    return cap_by_volume(trends, max_trends), fetch_errors


def dedupe_projected_queries(
    projections: list[tuple[Trend, str | None, dict[str, str] | None]],
) -> tuple[list[tuple[Trend, str | None, dict[str, str] | None]], int]:
    passthrough = [p for p in projections if p[1] is None]
    successes = sorted(
        ((trend, text) for trend, text, _err in projections if text is not None),
        key=lambda p: approx_traffic_value(p[0].approx_traffic),
        reverse=True,
    )
    kept: list[tuple[Trend, str | None, dict[str, str] | None]] = []
    norms: list[str] = []
    dropped = 0
    for trend, text in successes:
        norm = _normalize(text, QUERY_DEDUP_FLUFF_RE)
        if any(fuzz.token_set_ratio(norm, n) >= QUERY_DEDUP_THRESHOLD for n in norms):
            dropped += 1
            continue
        norms.append(norm)
        kept.append((trend, text, None))
    return passthrough + kept, dropped
