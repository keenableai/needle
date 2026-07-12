import json
from datetime import UTC, datetime

import pytest

from keenbench.freshstream import cli as freshstream_cli
from keenbench.rarestream import cli as rarestream_cli
from keenbench.shared import cli as shared_cli
from keenbench.shared import llm as llm_module
from keenbench.shared.llm import LLMClientError, OpenRouterClient, _content_to_text
from keenbench.shared.search import factory as search_factory


def test_run_rejects_unsupported_source():
    with pytest.raises(SystemExit):
        freshstream_cli.Freshstream().generate(source="bogus")


def test_trending_rejects_rss_only_flags():
    with pytest.raises(SystemExit):
        freshstream_cli.Freshstream().generate(source="trending", feeds="x.toml")


def test_rss_rejects_trends_only_flags():
    with pytest.raises(SystemExit):
        freshstream_cli.Freshstream().generate(source="rss", max_trends=5)


def test_trending_rejects_rss_only_flag_at_default_value():
    with pytest.raises(SystemExit):
        freshstream_cli.Freshstream().generate(source="trending", min_candidates=30)


def test_rss_rejects_trends_only_flag_at_default_value():
    with pytest.raises(SystemExit):
        freshstream_cli.Freshstream().generate(source="rss", geos="us-all")


def test_run_rejects_bad_feeds_file(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    with pytest.raises(SystemExit):
        freshstream_cli.Freshstream().generate(feeds=str(tmp_path / "does-not-exist.toml"))


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


async def test_chat_retries_transient_errors(monkeypatch):
    class FailResp:
        status_code = 503
        text = "unavailable"

    class OkResp:
        status_code = 200

        def json(self):
            return {
                "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

    calls = {"n": 0}

    class FakeHttp:
        async def post(self, url, **kwargs):
            calls["n"] += 1
            return FailResp() if calls["n"] < 3 else OkResp()

    monkeypatch.setattr(llm_module, "RETRY_DELAY_S", 0.0)
    c = OpenRouterClient(api_key="x", model="m")
    monkeypatch.setattr(c, "_http", lambda: FakeHttp())
    result = await c.chat([{"role": "user", "content": "q"}], max_tokens=5)
    assert result.content == "hi"
    assert calls["n"] == 3


async def test_chat_does_not_retry_client_errors(monkeypatch):
    class FailResp:
        status_code = 400
        text = "bad request"

    calls = {"n": 0}

    class FakeHttp:
        async def post(self, url, **kwargs):
            calls["n"] += 1
            return FailResp()

    c = OpenRouterClient(api_key="x", model="m")
    monkeypatch.setattr(c, "_http", lambda: FakeHttp())
    with pytest.raises(LLMClientError) as exc_info:
        await c.chat([{"role": "user", "content": "q"}], max_tokens=5)
    assert exc_info.value.error_type == "http_error"
    assert calls["n"] == 1


async def test_chat_raises_on_empty_response(monkeypatch):
    class FakeResp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": None}, "finish_reason": "stop"}]}

    class FakeHttp:
        async def post(self, url, **kwargs):
            return FakeResp()

    c = OpenRouterClient(api_key="x", model="m")
    monkeypatch.setattr(c, "_http", lambda: FakeHttp())
    with pytest.raises(LLMClientError) as exc_info:
        await c.chat([{"role": "user", "content": "q"}], max_tokens=5)
    assert exc_info.value.error_type == "empty_response"


def test_freshstream_run_passes_keenable_api_key(monkeypatch, tmp_path):
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
    freshstream_cli.Freshstream().run(
        queries=str(qfile), engines="keenable", out=str(tmp_path / "r.json")
    )
    assert created == {"api_key": "kb-key", "mode": "pro"}


def test_freshstream_run_load_rows_and_per_query_today(tmp_path):
    f = tmp_path / "q.jsonl"
    f.write_text(
        '{"query_text": "a", "topical_domain": "tech", "hour_ts": "2026-07-01T14:00:00+00:00"}\n'
        "plain text query\n"
    )
    rows = freshstream_cli._load_query_rows(str(f))
    assert rows[0]["topical_domain"] == "tech"
    assert freshstream_cli._today_for_row(rows[0], "1999-01-01") == "2026-07-01"
    assert freshstream_cli._today_for_row(rows[1], "1999-01-01") == "1999-01-01"


def test_freshstream_run_loader_keeps_scalar_lines_and_rejects_missing_file(tmp_path):
    f = tmp_path / "q.jsonl"
    f.write_text("1984\n")
    assert freshstream_cli._load_query_rows(str(f))[0]["query_text"] == "1984"
    with pytest.raises(SystemExit):
        freshstream_cli._load_query_rows(str(tmp_path / "missing.jsonl"))


def test_freshstream_run_rejects_unknown_sample(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    f = tmp_path / "q.jsonl"
    f.write_text("a\nb\n")
    with pytest.raises(SystemExit):
        freshstream_cli.Freshstream().run(queries=str(f), limit=1, sample="bogus")


def test_rarestream_generate_writes_sample(tmp_path):
    src = tmp_path / "filtered.jsonl"
    src.write_text(
        '{"query_text": "a", "length_bucket": "medium"}\n'
        '{"query_text": "b", "length_bucket": "long"}\n'
    )
    out = tmp_path / "o.jsonl"
    rarestream_cli.Rarestream().generate(queries=str(src), out=str(out), limit=1, sample="head")
    lines = [ln for ln in out.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1


def test_rarestream_run_requires_openrouter_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    f = tmp_path / "q.jsonl"
    f.write_text('{"query_text": "a"}\n')
    with pytest.raises(SystemExit):
        rarestream_cli.Rarestream().run(queries=str(f))


def test_rarestream_run_evaluates(tmp_path, monkeypatch):
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
    rarestream_cli.Rarestream().run(queries=str(f), engines="keenable", out=str(out))
    assert json.loads(out.read_text())["num_queries"] == 1
