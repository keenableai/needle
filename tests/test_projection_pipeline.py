import json
from datetime import UTC, datetime

from keenbench.freshstream.pipeline import _rss_provenance
from keenbench.freshstream.projection import project_all, project_one


class FakeLLM:
    def __init__(self, replies):
        self._replies = list(replies)

    async def complete(self, prompt, *, max_tokens, reasoning_effort):
        return self._replies.pop(0)


async def test_project_one_cleans_query():
    llm = FakeLLM([('  "Lakers trade deadline"\nextra line ', None)])
    query, err = await project_one(llm, {"title": "t"})
    assert query == "Lakers trade deadline"
    assert err is None


async def test_project_one_no_news_event_is_not_error():
    llm = FakeLLM([("NO_NEWS_EVENT", None)])
    query, err = await project_one(llm, {"title": "t"})
    assert query is None and err is None


async def test_project_one_error_passthrough():
    llm = FakeLLM([(None, {"error_type": "http_error", "error_message": "500"})])
    query, err = await project_one(llm, {"title": "t"})
    assert query is None and err == {"error_type": "http_error", "error_message": "500"}


async def test_project_all_preserves_records():
    llm = FakeLLM([("query one", None), ("NO_NEWS_EVENT", None)])
    recs = [{"title": "a"}, {"title": "b"}]
    out = await project_all(llm, recs, concurrency=2)
    assert {r["title"] for r, _, _ in out} == {"a", "b"}


async def test_run_rss_end_to_end(monkeypatch):
    import keenbench.freshstream.pipeline as pipeline

    fake_items = [
        {
            "parent_site": "https://ex.com/feed",
            "source_kind": "rss_news",
            "topical_domain_default": "tech",
            "lastmod_or_pub_at": "Wed, 01 Jul 2026 13:30:00 GMT",
            "title": "Acme ships thing",
            "url": "https://ex.com/a",
            "summary": "s",
        }
    ]

    async def fake_fetch(sources, *, max_rows_per_source, concurrency):
        return fake_items, [{"source_url": "https://ex.com/feed", "parse_ok": True}]

    monkeypatch.setattr(pipeline, "fetch_all_sources", fake_fetch)

    llm = FakeLLM([("acme thing launch", None)])
    now = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    rows, stats = await pipeline.run_rss((), llm, hour_ts=now, now=now, llm_concurrency=1)

    assert len(rows) == 1
    row = rows[0]
    assert row.query_text == "acme thing launch"
    assert row.query_source == "fresh-queries"
    origin = json.loads(row.query_origin)
    assert origin["bucket"] == "rss"
    assert origin["topical_domain"] == "tech"
    assert origin["subcategory"] == "rss_tech"
    assert origin["provenance"]["url"] == "https://ex.com/a"
    assert stats.projected == 1 and stats.candidates == 1


def test_rss_provenance_shape():
    p = _rss_provenance({"source_kind": "rss_news", "url": "u", "title": "t"})
    assert p["producer"] == "rss_queries"
    assert p["url"] == "u"
