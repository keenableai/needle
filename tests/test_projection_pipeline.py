from datetime import UTC, datetime

import pytest

from keenbench.freshstream.models import build_query_row
from keenbench.freshstream.pipeline import _rss_provenance, run_rss
from keenbench.freshstream.projection import (
    build_projection_prompt,
    clean_projection,
    project_batch,
)
from keenbench.shared.sampling import sample_stratified

TODAY = "2026-07-01"


class FakeLLM:
    def __init__(self, reply):
        self._reply = reply

    async def complete(self, prompt, *, max_tokens, reasoning_effort):
        return self._reply


class BoomLLM:
    async def complete(self, prompt, *, max_tokens, reasoning_effort):
        raise RuntimeError("boom")


def test_clean_projection():
    assert clean_projection('  "Lakers trade deadline"\nextra line ') == "Lakers trade deadline"
    assert clean_projection("NO_NEWS_EVENT") is None
    assert clean_projection("NO_NEWS_EVENT.") is None
    assert clean_projection("Answer: NO_NEWS_EVENT") is None
    assert clean_projection("no news event blackout 2026") == "no news event blackout 2026"
    assert clean_projection(None) is None
    assert clean_projection("  \n  ") is None


async def test_project_batch_cleans_and_passes_errors():
    llm = FakeLLM(("  query one  ", None))
    out = await project_batch(llm, [{"title": "a"}], build_projection_prompt_today, concurrency=1)
    item, query, err = out[0]
    assert item == {"title": "a"} and query == "query one" and err is None

    errllm = FakeLLM((None, {"error_type": "http_error", "error_message": "500"}))
    _, query, err = (await project_batch(errllm, [{"title": "a"}], build_projection_prompt_today))[
        0
    ]
    assert query is None and err["error_type"] == "http_error"


async def test_project_batch_preserves_items_and_survives_crash():
    out = await project_batch(BoomLLM(), [{"title": "a"}], build_projection_prompt_today)
    item, text, err = out[0]
    assert item == {"title": "a"} and text is None and err["error_type"] == "projection_crash"


async def test_project_batch_rejects_zero_concurrency():
    with pytest.raises(ValueError):
        await project_batch(FakeLLM((None, None)), [], build_projection_prompt_today, concurrency=0)


def build_projection_prompt_today(record):
    return build_projection_prompt(record, today=TODAY)


def test_build_projection_prompt_uses_explicit_today():
    prompt = build_projection_prompt({"title": "t"}, today="2020-01-01")
    assert "Today's date: 2020-01-01" in prompt


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
            "observed_at": datetime(2026, 7, 1, 14, 0, tzinfo=UTC),
        }
    ]

    async def fake_fetch(sources, *, max_rows_per_source, concurrency):
        return fake_items, [{"source_url": "https://ex.com/feed", "parse_ok": True}]

    monkeypatch.setattr(pipeline, "fetch_all_sources", fake_fetch)

    llm = FakeLLM(("acme thing launch", None))
    hour_ts = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    rows, stats = await pipeline.run_rss((), llm, hour_ts=hour_ts, llm_concurrency=1)

    assert len(rows) == 1
    row = rows[0]
    assert row.query_text == "acme thing launch"
    assert row.query_source == "fresh-queries"
    assert row.topical_domain == "tech"
    origin = row.query_origin
    assert origin["bucket"] == "rss"
    assert origin["topical_domain"] == "tech"
    assert origin["subcategory"] == "rss_tech"
    assert origin["provenance"]["url"] == "https://ex.com/a"
    assert stats.projected == 1 and stats.candidates == 1


async def test_run_rss_rejects_negative_min_candidates():
    hour_ts = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        await run_rss((), FakeLLM((None, None)), hour_ts=hour_ts, min_candidates=-1)


def test_emitted_rows_are_stratifiable():
    row = build_query_row(
        query_text="acme launch",
        hour_ts=datetime(2026, 7, 1, 14, 0, tzinfo=UTC),
        bucket="rss",
        topical_domain="tech",
        provenance={},
    )
    picked = sample_stratified([row.to_dict()], 1, seed=1)
    assert len(picked) == 1
    assert picked[0]["topical_domain"] == "tech"


def test_rss_provenance_shape():
    p = _rss_provenance({"source_kind": "rss_news", "url": "u", "title": "t"})
    assert p["producer"] == "rss_queries"
    assert p["url"] == "u"
