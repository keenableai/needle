from dataclasses import dataclass
from typing import Protocol
from xml.etree.ElementTree import ParseError

import defusedxml.ElementTree as ET
import httpx
from defusedxml.common import DefusedXmlException

from keenbench.freshstream.feeds import HTTP_TIMEOUT, _text_of

HT_NS = {"ht": "https://trends.google.com/trending/rss"}
USER_AGENT = "Mozilla/5.0 (compatible; keenbench-freshstream/0.1)"


@dataclass(frozen=True)
class NewsItem:
    title: str | None
    url: str | None
    source: str | None


@dataclass(frozen=True)
class Trend:
    topic: str
    approx_traffic: str | None
    news_items: tuple[NewsItem, ...]


class TrendsProvider(Protocol):
    async def fetch(self) -> list[Trend]: ...


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
