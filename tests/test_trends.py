import json
from datetime import UTC, datetime

import pytest

from needle.news.pipeline import run_trends
from needle.news.projection import build_trend_prompt
from needle.news.trends import (
    US_GEOS,
    GoogleTrendsRssProvider,
    NewsItem,
    Trend,
    approx_traffic_value,
    cap_by_volume,
    collect_unique_trends,
    dedupe_projected_queries,
    dedupe_topics,
    fetch_all_geos,
    filter_ascii_topics,
    parse_trends,
)

NOW = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
FRESH_PUB = "2026-07-01T13:30:00+00:00"
STALE_PUB = "2026-06-25T00:00:00+00:00"
FUTURE_PUB = "2026-07-05T00:00:00+00:00"

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


def trend(topic, traffic=None, pub=FRESH_PUB, news=(), geos=()):
    return Trend(
        topic=topic,
        approx_traffic=traffic,
        pub_date=pub,
        news_items=tuple(news),
        geos=tuple(geos),
    )


class FakeProvider:
    def __init__(self, by_geo):
        self._by_geo = by_geo

    async def fetch(self, geo):
        val = self._by_geo[geo]
        if isinstance(val, Exception):
            raise val
        return val


class FakeLLM:
    async def complete(self, prompt, *, max_tokens, reasoning_effort):
        if "vucevic" in prompt:
            return "vucevic magic deal 2026", None
        return "NO_NEWS_EVENT", None


def test_us_geos_covers_states():
    assert len(US_GEOS) == 52
    assert "US" in US_GEOS and "US-CA" in US_GEOS


def test_parse_trends():
    trends = parse_trends(SAMPLE)
    assert [t.topic for t in trends] == ["nikola vucevic", "no news topic"]
    t = trends[0]
    assert t.approx_traffic == "500+"
    assert len(t.news_items) == 1
    assert t.news_items[0].title == "Vucevic reuniting with Magic on 1-year deal"
    assert t.news_items[0].source == "ESPN"
    assert t.pub_date == "Wed, 1 Jul 2026 08:20:00 -0700"
    assert trends[1].news_items == ()
    assert trends[1].pub_date is None


def test_approx_traffic_value():
    assert approx_traffic_value("500+") == 500
    assert approx_traffic_value("1,000,000+") == 1_000_000
    assert approx_traffic_value("2M+") == 2_000_000
    assert approx_traffic_value("50K+") == 50_000
    assert approx_traffic_value(None) == 0
    assert approx_traffic_value("garbage") == 0


def test_collect_unique_trends_merges_geos():
    a = trend("lakers")
    merged = collect_unique_trends({"US": [a], "US-CA": [trend("lakers")], "US-NY": [trend("x")]})
    by_topic = {t.topic: t for t in merged}
    assert by_topic["lakers"].geos == ("US", "US-CA")
    assert by_topic["x"].geos == ("US-NY",)


def test_dedupe_topics_fuzzy_merges_and_keeps_highest_volume():
    trends = [
        trend("Lakers vs Warriors", "500+", geos=("US",)),
        trend("warriors lakers", "10,000+", geos=("US-CA",)),
        trend("unrelated topic", "200+", geos=("US",)),
    ]
    deduped = dedupe_topics(trends)
    topics = [t.topic for t in deduped]
    assert "warriors lakers" in topics
    assert "Lakers vs Warriors" not in topics
    survivor = next(t for t in deduped if t.topic == "warriors lakers")
    assert set(survivor.geos) == {"US", "US-CA"}
    assert "unrelated topic" in topics


def test_filter_ascii_topics():
    kept = filter_ascii_topics([trend("lakers"), trend("東京オリンピック")])
    assert [t.topic for t in kept] == ["lakers"]


def test_cap_by_volume_keeps_top_by_traffic():
    trends = [trend("low", "100+"), trend("high", "10,000+"), trend("mid", "500+")]
    assert [t.topic for t in cap_by_volume(trends, 2)] == ["high", "mid"]
    assert cap_by_volume(trends, 0) == trends


def test_dedupe_projected_queries_collapses_near_duplicates():
    high = trend("a", "10,000+")
    low = trend("b", "100+")
    other = trend("c", "50+")
    projections = [
        (low, "lakers warriors game score", None),
        (high, "Lakers vs Warriors score 2026", None),
        (other, "senate budget vote", None),
        (trend("err"), None, {"error_type": "x", "error_message": "y"}),
        (trend("refused"), None, None),
    ]
    kept, dropped = dedupe_projected_queries(projections)
    texts = [t for _, t, _ in kept if t]
    assert dropped == 1
    assert "Lakers vs Warriors score 2026" in texts
    assert "lakers warriors game score" not in texts
    assert "senate budget vote" in texts
    assert sum(1 for _, t, _ in kept if t is None) == 2


async def test_fetch_all_geos_fail_soft():
    provider = FakeProvider({"US": [trend("a")], "US-CA": ValueError("down")})
    by_geo, errors = await fetch_all_geos(provider, ("US", "US-CA"))
    assert errors == 1
    assert list(by_geo) == ["US"]


def test_build_trend_prompt_has_topic_and_news():
    t = trend(
        "nikola vucevic",
        "500+",
        news=(NewsItem(title="Vucevic to Magic", url="u", source="ESPN"),),
    )
    prompt = build_trend_prompt(t, today="2026-07-01")
    assert "Today's date: 2026-07-01" in prompt
    assert "Trending topic: nikola vucevic" in prompt
    assert "[ESPN] Vucevic to Magic" in prompt


async def test_run_trends_end_to_end():
    news = (NewsItem("Vucevic to Magic", "u", "ESPN"),)
    by_geo = {
        "US": [trend("vucevic", "500+", news=news), trend("evergreen", "200+")],
        "US-FL": [trend("vucevic", "500+", news=news)],
    }
    rows, stats = await run_trends(
        FakeProvider(by_geo),
        FakeLLM(),
        hour_ts=NOW,
        now=NOW,
        geos=("US", "US-FL"),
        llm_concurrency=2,
    )

    assert stats.candidates == 2
    assert stats.projected == 1
    assert stats.no_news_event == 1
    assert stats.fetch_errors == 0
    row = rows[0]
    assert row.query_text == "vucevic magic deal 2026"
    assert row.query_source == "fresh-queries"
    origin = row.query_origin
    assert origin["bucket"] == "trending"
    assert origin["subcategory"] == "google_trends"
    assert origin["provenance"]["producer"] == "trends_queries"
    assert origin["provenance"]["topic"] == "vucevic"
    assert origin["provenance"]["pub_date"] == FRESH_PUB
    assert origin["provenance"]["geos"] == ["US", "US-FL"]
    assert origin["provenance"]["geo_count"] == 2
    wire = json.loads(json.dumps(row.to_dict()))
    assert json.loads(wire["query_origin"])["bucket"] == "trending"


async def test_run_trends_drops_stale_future_and_undated():
    news = (NewsItem("vucevic", "u", "ESPN"),)
    by_geo = {
        "US": [
            trend("fresh", "1", FRESH_PUB, news),
            trend("stale", "1", STALE_PUB, news),
            trend("future", "1", FUTURE_PUB, news),
            trend("undated", "1", None, news),
        ]
    }
    rows, stats = await run_trends(
        FakeProvider(by_geo), FakeLLM(), hour_ts=NOW, now=NOW, geos=("US",)
    )
    assert stats.candidates == 1
    assert stats.projected == 1
    assert rows[0].query_origin["provenance"]["topic"] == "fresh"


async def test_run_trends_caps_by_volume():
    news = (NewsItem("vucevic", "u", "ESPN"),)
    topics = ["lakers game", "senate vote", "hurricane update", "iphone launch"]
    by_geo = {"US": [trend(t, f"{(i + 1) * 100}+", news=news) for i, t in enumerate(topics)]}
    rows, stats = await run_trends(
        FakeProvider(by_geo), FakeLLM(), hour_ts=NOW, now=NOW, geos=("US",), max_trends=2
    )
    assert stats.candidates == 2


async def test_fetch_wraps_http_errors_as_valueerror():
    provider = GoogleTrendsRssProvider(base_url="http://127.0.0.1:1", timeout_s=2.0)
    with pytest.raises(ValueError):
        await provider.fetch("US")
