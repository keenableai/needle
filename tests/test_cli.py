import json
from datetime import UTC, datetime

import pytest

from keenbench.agentic_rare import cli as agentic_rare_cli
from keenbench.news import cli as news_cli
from keenbench.shared import cli as shared_cli
from keenbench.shared.llm import OpenRouterClient, _content_to_text
from keenbench.shared.search import DEFAULT_SNIPPET_CHARS
from keenbench.shared.search import factory as search_factory


def test_run_rejects_unsupported_source():
    with pytest.raises(SystemExit):
        news_cli.News().generate(source="bogus")


def test_trending_rejects_rss_only_flags():
    with pytest.raises(SystemExit):
        news_cli.News().generate(source="trending", feeds="x.toml")


def test_rss_rejects_trends_only_flags():
    with pytest.raises(SystemExit):
        news_cli.News().generate(source="rss", max_trends=5)


def test_trending_rejects_rss_only_flag_at_default_value():
    with pytest.raises(SystemExit):
        news_cli.News().generate(source="trending", min_candidates=30)


def test_rss_rejects_trends_only_flag_at_default_value():
    with pytest.raises(SystemExit):
        news_cli.News().generate(source="rss", geos="us-all")


def test_run_rejects_bad_feeds_file(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    with pytest.raises(SystemExit):
        news_cli.News().generate(feeds=str(tmp_path / "does-not-exist.toml"))


def test_resolve_seed_explicit_passthrough_and_time_varying():
    ts1 = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    ts2 = datetime(2026, 7, 2, 14, 0, tzinfo=UTC)
    assert shared_cli.resolve_seed(42, ts1) == 42
    assert shared_cli.resolve_seed(0, ts1) == 0
    assert shared_cli.resolve_seed(None, ts1) == shared_cli.resolve_seed(None, ts1)
    assert shared_cli.resolve_seed(None, ts1) != shared_cli.resolve_seed(None, ts2)


def test_sample_or_exit_accepts_none_seed():
    rows = [{"query_text": str(i), "topical_domain": "t"} for i in range(30)]
    assert len(shared_cli.sample_or_exit(rows, 5, None, strategy="stratified")) == 5


def test_openrouter_default_temperature_is_deterministic():
    assert OpenRouterClient(api_key="x", model="m").temperature == 0.0


def test_content_to_text_handles_str_list_and_none():
    assert _content_to_text("hi") == "hi"
    assert _content_to_text([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]) == "ab"
    assert _content_to_text(None) is None
    assert _content_to_text([]) == ""


async def test_openrouter_reports_truncation(monkeypatch):
    class FakeResp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "partial"}, "finish_reason": "length"}]}

    class FakeHttp:
        async def post(self, url, **kwargs):
            return FakeResp()

    c = OpenRouterClient(api_key="x", model="m")
    monkeypatch.setattr(c, "_http", lambda: FakeHttp())
    text, err = await c.complete("p", max_tokens=5, reasoning_effort="none")
    assert text is None and err["error_type"] == "truncated"


def test_news_run_passes_keenable_api_key(monkeypatch, tmp_path):
    qfile = tmp_path / "q.jsonl"
    qfile.write_text("mayor of austin\n")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("KEENABLE_API_KEY", "kb-key")

    created = {}

    class FakeKeenable:
        def __init__(self, **kwargs):
            created.update(kwargs)

        async def aclose(self):
            pass

    async def fake_run_rbp(queries, clients, judge, **kwargs):
        return {"num_queries": len(queries), "num_results": 5, "engines": {}}

    monkeypatch.setattr(search_factory, "KeenableClient", FakeKeenable)
    monkeypatch.setattr(shared_cli, "run_rbp", fake_run_rbp)
    news_cli.News().run(queries=str(qfile), engines="keenable", out=str(tmp_path / "r.json"))
    assert created == {
        "api_key": "kb-key",
        "mode": "pro",
        "snippet_chars": DEFAULT_SNIPPET_CHARS,
    }


def test_news_run_load_rows_and_per_query_today(tmp_path):
    f = tmp_path / "q.jsonl"
    f.write_text(
        '{"query_text": "a", "topical_domain": "tech", "hour_ts": "2026-07-01T14:00:00+00:00"}\n'
        "plain text query\n"
    )
    rows = news_cli._load_query_rows(str(f))
    assert rows[0]["topical_domain"] == "tech"
    assert news_cli._today_for_row(rows[0], "1999-01-01") == "2026-07-01"
    assert news_cli._today_for_row(rows[1], "1999-01-01") == "1999-01-01"


def test_news_run_loader_keeps_scalar_lines_and_rejects_missing_file(tmp_path):
    f = tmp_path / "q.jsonl"
    f.write_text("1984\n")
    assert news_cli._load_query_rows(str(f))[0]["query_text"] == "1984"
    with pytest.raises(SystemExit):
        news_cli._load_query_rows(str(tmp_path / "missing.jsonl"))


def test_news_run_rejects_unknown_sample(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    f = tmp_path / "q.jsonl"
    f.write_text("a\nb\n")
    with pytest.raises(SystemExit):
        news_cli.News().run(queries=str(f), limit=1, sample="bogus")


def test_agentic_rare_generate_writes_sample(tmp_path):
    src = tmp_path / "filtered.jsonl"
    src.write_text(
        '{"query_text": "a", "length_bucket": "medium"}\n'
        '{"query_text": "b", "length_bucket": "long"}\n'
    )
    out = tmp_path / "o.jsonl"
    agentic_rare_cli.AgenticRare().generate(queries=str(src), out=str(out), limit=1, sample="head")
    lines = [ln for ln in out.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1


def test_agentic_rare_run_requires_openrouter_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    f = tmp_path / "q.jsonl"
    f.write_text('{"query_text": "a"}\n')
    with pytest.raises(SystemExit):
        agentic_rare_cli.AgenticRare().run(queries=str(f))


def test_agentic_rare_run_evaluates(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("KEENABLE_API_KEY", "kb-key")
    f = tmp_path / "q.jsonl"
    f.write_text('{"query_text": "rare thing", "length_bucket": "medium"}\n')

    class FakeKeenable:
        def __init__(self, **kwargs):
            pass

        async def aclose(self):
            pass

    async def fake_run_rbp(eval_queries, clients, judge, **kwargs):
        return {"num_queries": len(eval_queries), "engines": {}}

    monkeypatch.setattr(search_factory, "KeenableClient", FakeKeenable)
    monkeypatch.setattr(shared_cli, "run_rbp", fake_run_rbp)
    out = tmp_path / "r.json"
    agentic_rare_cli.AgenticRare().run(queries=str(f), engines="keenable", out=str(out))
    assert json.loads(out.read_text())["num_queries"] == 1
