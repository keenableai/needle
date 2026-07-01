import json
from datetime import UTC, datetime

import pytest

from keenbench.freshstream.pipeline import run_trends
from keenbench.freshstream.projection import build_trend_prompt
from keenbench.freshstream.trends import GoogleTrendsRssProvider, NewsItem, Trend, parse_trends

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:ht="https://trends.google.com/trending/rss" version="2.0"><channel>
<item>
  <title>nikola vucevic</title>
  <ht:approx_traffic>500+</ht:approx_traffic>
  <pubDate>Wed, 1 Jul 2026 08:20:00 -0700</pubDate>
  <ht:news_item>
    <ht:news_item_title>Vucevic reuniting with Magic on 1-year deal</ht:news_item_title>
    <ht:news_item_url>https://espn.com/x</ht:news_item_url>
    <ht:news_item_source>ESPN</ht:news_item_source>
  </ht:news_item>
</item>
<item>
  <title>no news topic</title>
  <ht:approx_traffic>200+</ht:approx_traffic>
</item>
</channel></rss>"""


class FakeProvider:
    def __init__(self, trends):
        self._trends = trends

    async def fetch(self):
        return self._trends


class FakeLLM:
    async def complete(self, prompt, *, max_tokens, reasoning_effort):
        if "vucevic" in prompt:
            return "vucevic magic deal 2026", None
        return "NO_NEWS_EVENT", None


def test_parse_trends():
    trends = parse_trends(SAMPLE)
    assert [t.topic for t in trends] == ["nikola vucevic", "no news topic"]
    t = trends[0]
    assert t.approx_traffic == "500+"
    assert len(t.news_items) == 1
    assert t.news_items[0].title == "Vucevic reuniting with Magic on 1-year deal"
    assert t.news_items[0].source == "ESPN"
    assert trends[1].news_items == ()


def test_build_trend_prompt_has_topic_and_news():
    trend = Trend(
        topic="nikola vucevic",
        approx_traffic="500+",
        pub_date=None,
        news_items=(NewsItem(title="Vucevic to Magic", url="u", source="ESPN", snippet=None),),
    )
    prompt = build_trend_prompt(trend, today="2026-07-01")
    assert "Today's date: 2026-07-01" in prompt
    assert "Trending topic: nikola vucevic" in prompt
    assert "[ESPN] Vucevic to Magic" in prompt


async def test_run_trends_end_to_end():
    trends = [
        Trend("vucevic", "500+", None, (NewsItem("Vucevic to Magic", "u", "ESPN", None),)),
        Trend("evergreen", "200+", None, ()),
    ]
    llm = FakeLLM()
    hour_ts = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    rows, stats = await run_trends(FakeProvider(trends), llm, hour_ts=hour_ts, llm_concurrency=2)

    assert stats.candidates == 2
    assert stats.projected == 1
    assert stats.no_news_event == 1
    row = rows[0]
    assert row.query_text == "vucevic magic deal 2026"
    assert row.query_source == "fresh-queries"
    origin = row.query_origin
    assert origin["bucket"] == "trending"
    assert origin["subcategory"] == "google_trends"
    assert origin["provenance"]["producer"] == "trends_queries"
    assert origin["provenance"]["topic"] == "vucevic"
    assert json.loads(json.dumps(row.to_dict()))["query_origin"]["bucket"] == "trending"


async def test_run_trends_respects_max_trends():
    trends = [
        Trend(f"t{i}", None, None, (NewsItem("vucevic", "u", "ESPN", None),)) for i in range(5)
    ]
    rows, stats = await run_trends(
        FakeProvider(trends), FakeLLM(), hour_ts=datetime(2026, 7, 1, tzinfo=UTC), max_trends=2
    )
    assert stats.candidates == 2


async def test_fetch_wraps_http_errors_as_valueerror():
    provider = GoogleTrendsRssProvider(base_url="http://127.0.0.1:1", timeout_s=2.0)
    with pytest.raises(ValueError):
        await provider.fetch()
