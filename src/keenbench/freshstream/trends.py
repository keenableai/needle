from dataclasses import dataclass
from typing import Protocol
from xml.etree.ElementTree import Element, ParseError

import defusedxml.ElementTree as ET
import httpx
from defusedxml.common import DefusedXmlException

HT_NS = {"ht": "https://trends.google.com/trending/rss"}
USER_AGENT = "Mozilla/5.0 (compatible; keenbench-freshstream/0.1)"
HTTP_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


@dataclass(frozen=True)
class NewsItem:
    title: str | None
    url: str | None
    source: str | None
    snippet: str | None


@dataclass(frozen=True)
class Trend:
    topic: str
    approx_traffic: str | None
    pub_date: str | None
    news_items: tuple[NewsItem, ...]


class TrendsProvider(Protocol):
    async def fetch(self) -> list[Trend]: ...


def _text(el: Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    return el.text.strip() or None


def parse_trends(xml: str) -> list[Trend]:
    root = ET.fromstring(xml)
    trends: list[Trend] = []
    for item in root.findall(".//item"):
        topic = _text(item.find("title"))
        if not topic:
            continue
        news = [
            NewsItem(
                title=_text(n.find("ht:news_item_title", HT_NS)),
                url=_text(n.find("ht:news_item_url", HT_NS)),
                source=_text(n.find("ht:news_item_source", HT_NS)),
                snippet=_text(n.find("ht:news_item_snippet", HT_NS)),
            )
            for n in item.findall("ht:news_item", HT_NS)
        ]
        trends.append(
            Trend(
                topic=topic,
                approx_traffic=_text(item.find("ht:approx_traffic", HT_NS)),
                pub_date=_text(item.find("pubDate")),
                news_items=tuple(news),
            )
        )
    return trends


class GoogleTrendsRssProvider:
    def __init__(
        self,
        *,
        geo: str = "US",
        base_url: str = "https://trends.google.com/trending/rss",
        timeout_s: float | None = None,
    ) -> None:
        self.geo = geo
        self.base_url = base_url
        self.timeout = httpx.Timeout(timeout_s) if timeout_s else HTTP_TIMEOUT

    async def fetch(self) -> list[Trend]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    self.base_url,
                    params={"geo": self.geo},
                    headers={"User-Agent": USER_AGENT},
                    follow_redirects=True,
                )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ValueError(
                f"could not fetch Google Trends RSS (geo={self.geo}): {type(exc).__name__}: {exc}"
            ) from exc
        try:
            return parse_trends(resp.text)
        except (ParseError, DefusedXmlException) as exc:
            raise ValueError(f"could not parse Google Trends RSS: {exc}") from exc
