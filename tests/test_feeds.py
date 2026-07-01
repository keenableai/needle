from datetime import UTC, datetime, timedelta

import defusedxml.ElementTree as ET
import pytest

from keenbench.freshstream import feeds as feeds_mod
from keenbench.freshstream.feeds import (
    SEED_SOURCES,
    SeedSource,
    _fetch_one,
    _FetchOutcome,
    _parse_feed,
    fetch_all_sources,
    load_sources_from_toml,
    parse_published_date,
    pick_per_feed,
)


async def test_fetch_all_sources_rejects_zero_concurrency():
    with pytest.raises(ValueError):
        await fetch_all_sources((), concurrency=0)


async def test_fetch_all_sources_rejects_zero_max_rows():
    with pytest.raises(ValueError):
        await fetch_all_sources((), max_rows_per_source=0)


ENTITY_BOMB = (
    '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x "y">]>'
    "<rss><channel><item><title>&x;</title></item></channel></rss>"
)


def _rfc822(dt):
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


async def _run_fetch_one(monkeypatch, xml, *, max_rows=50):
    async def fake_fetch_text(client, url):
        return _FetchOutcome(text=xml, http_status=200, fetch_error_class=None)

    monkeypatch.setattr(feeds_mod, "_fetch_text", fake_fetch_text)
    src = SeedSource("https://ex.com/feed", "rss_news", "tech")
    return await _fetch_one(None, src, max_rows_per_source=max_rows)


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


def test_parse_atom_link_prefers_alternate():
    atom = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>T</title>
        <link rel="self" href="https://ex.com/entry.atom"/>
        <link rel="alternate" href="https://ex.com/article"/>
      </entry>
    </feed>"""
    entries = _parse_feed(ET.fromstring(atom))
    assert entries[0]["url"] == "https://ex.com/article"


def test_parse_rss1_rdf_items():
    rdf = """<?xml version="1.0"?>
    <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
             xmlns="http://purl.org/rss/1.0/"
             xmlns:dc="http://purl.org/dc/elements/1.1/">
      <item rdf:about="https://ex.com/p">
        <title>Paper</title><link>https://ex.com/p</link>
        <description>abs</description><dc:date>2026-07-01T13:00:00Z</dc:date>
      </item>
    </rdf:RDF>"""
    entries = _parse_feed(ET.fromstring(rdf))
    assert entries[0]["title"] == "Paper"
    assert entries[0]["url"] == "https://ex.com/p"
    assert entries[0]["published_at"] == "2026-07-01T13:00:00Z"


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
    two_days_ago = _rfc822(now - timedelta(hours=48))
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


async def test_fetch_one_drops_undated_items_so_they_cannot_crowd_out_fresh(monkeypatch):
    fresh = _rfc822(datetime.now(UTC) - timedelta(minutes=5))
    xml = (
        "<rss><channel>"
        "<item><title>undated1</title><link>https://x/1</link></item>"
        "<item><title>undated2</title><link>https://x/2</link></item>"
        f"<item><title>fresh</title><link>https://x/f</link><pubDate>{fresh}</pubDate></item>"
        "</channel></rss>"
    )
    items, health = await _run_fetch_one(monkeypatch, xml, max_rows=2)
    assert [i["title"] for i in items] == ["fresh"]
    assert health["items_total"] == 3


async def test_fetch_one_tolerates_small_future_skew(monkeypatch):
    now = datetime.now(UTC)
    skewed = _rfc822(now + timedelta(seconds=30))
    far_future = _rfc822(now + timedelta(hours=1))
    xml = (
        "<rss><channel>"
        f"<item><title>skewed</title><link>https://x/s</link><pubDate>{skewed}</pubDate></item>"
        f"<item><title>far</title><link>https://x/z</link><pubDate>{far_future}</pubDate></item>"
        "</channel></rss>"
    )
    items, health = await _run_fetch_one(monkeypatch, xml)
    assert [i["title"] for i in items] == ["skewed"]
    assert health["newest_item_age_minutes"] == 0.0
    assert health["items_lt_1h"] == 1


def test_pick_per_feed_tolerates_small_future_skew():
    now = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    items = [
        {
            "parent_site": "https://ex.com/feed",
            "source_kind": "rss_news",
            "lastmod_or_pub_at": _rfc822(now + timedelta(seconds=30)),
            "title": "skewed",
        }
    ]
    picked = pick_per_feed(items, now=now)
    assert [r["title"] for r in picked] == ["skewed"]


async def test_fetch_one_handles_defused_parse_failure(monkeypatch):
    items, health = await _run_fetch_one(monkeypatch, ENTITY_BOMB)
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
