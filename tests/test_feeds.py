from datetime import UTC, datetime, timedelta

import defusedxml.ElementTree as ET
import pytest

from keenbench.freshstream import feeds as feeds_mod
from keenbench.freshstream.feeds import (
    SEED_SOURCES,
    SeedSource,
    _FetchOutcome,
    _fetch_one,
    _parse_feed,
    fetch_all_sources,
    load_sources_from_toml,
    parse_published_date,
    pick_per_feed,
)


async def test_fetch_all_sources_rejects_zero_concurrency():
    with pytest.raises(ValueError):
        await fetch_all_sources((), concurrency=0)

ENTITY_BOMB = (
    '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x "y">]>'
    "<rss><channel><item><title>&x;</title></item></channel></rss>"
)

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>Alpha</title><description>d1</description>
    <link>https://ex.com/a</link><pubDate>Wed, 01 Jul 2026 13:30:00 GMT</pubDate></item>
  <item><title>Beta</title><description>d2</description>
    <link>https://ex.com/b</link><pubDate>Wed, 01 Jul 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><title>Gamma</title><summary>s</summary>
    <link href="https://ex.com/g"/><updated>2026-07-01T13:45:00Z</updated></entry>
</feed>"""


def test_parse_rss_items():
    entries = _parse_feed(ET.fromstring(RSS))
    assert [e["title"] for e in entries] == ["Alpha", "Beta"]
    assert entries[0]["url"] == "https://ex.com/a"


def test_parse_atom_entries():
    entries = _parse_feed(ET.fromstring(ATOM))
    assert entries[0]["title"] == "Gamma"
    assert entries[0]["url"] == "https://ex.com/g"


def test_parse_published_date_rss_and_iso():
    assert parse_published_date("Wed, 01 Jul 2026 13:30:00 GMT").hour == 13
    assert parse_published_date("2026-07-01T13:45:00Z").tzinfo is not None
    assert parse_published_date("garbage") is None
    assert parse_published_date(None) is None


def test_pick_per_feed_newest_within_window():
    now = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    items = [
        {
            "parent_site": "https://ex.com/feed",
            "source_kind": "rss_news",
            "lastmod_or_pub_at": "Wed, 01 Jul 2026 13:30:00 GMT",
            "title": "fresh",
        },
        {
            "parent_site": "https://ex.com/feed",
            "source_kind": "rss_news",
            "lastmod_or_pub_at": "Wed, 01 Jul 2026 10:00:00 GMT",
            "title": "stale",
        },
    ]
    picked = pick_per_feed(items, now=now)
    assert len(picked) == 1
    assert picked[0]["title"] == "fresh"


def test_pick_per_feed_paper_window_is_wider():
    now = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    two_days_ago = (now - timedelta(hours=48)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    items = [
        {
            "parent_site": "https://arxiv/feed",
            "source_kind": "rss_paper",
            "lastmod_or_pub_at": two_days_ago,
            "title": "paper",
        }
    ]
    assert len(pick_per_feed(items, now=now)) == 1


def test_pick_per_feed_drops_unparseable_dates():
    now = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    items = [
        {
            "parent_site": "https://ex.com/feed",
            "source_kind": "rss_news",
            "lastmod_or_pub_at": None,
            "title": "no date",
        }
    ]
    assert pick_per_feed(items, now=now) == []


def test_seed_sources_are_well_formed():
    kinds = {"rss_news", "rss_release", "rss_blog", "rss_paper", "rss_social"}
    assert len(SEED_SOURCES) > 100
    for s in SEED_SOURCES:
        assert s.url.startswith("http")
        assert s.source_kind in kinds


async def test_fetch_one_handles_defused_parse_failure(monkeypatch):
    async def fake_fetch_text(client, url):
        return _FetchOutcome(text=ENTITY_BOMB, http_status=200, fetch_error_class=None)

    monkeypatch.setattr(feeds_mod, "_fetch_text", fake_fetch_text)
    src = SeedSource("https://ex.com/feed", "rss_news", "tech")
    items, health = await _fetch_one(None, src, max_rows_per_source=50)
    assert items == []
    assert health["parse_ok"] is False


def test_load_sources_from_toml(tmp_path):
    p = tmp_path / "feeds.toml"
    p.write_text(
        '[[source]]\nurl = "https://ex.com/feed"\n'
        'source_kind = "rss_news"\ntopical_domain = "tech"\n'
    )
    sources = load_sources_from_toml(p)
    assert len(sources) == 1
    assert sources[0].url == "https://ex.com/feed"
    assert sources[0].topical_domain == "tech"
