import pytest

from keenbench.freshstream import cli as freshstream_cli
from keenbench.shared.llm import OpenRouterClient, _content_to_text
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


def test_run_rejects_bad_feeds_file(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    with pytest.raises(SystemExit):
        freshstream_cli.Freshstream().generate(feeds=str(tmp_path / "does-not-exist.toml"))


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
    monkeypatch.setattr(freshstream_cli, "run_rbp", fake_run_rbp)
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


def test_freshstream_run_rejects_unknown_sample(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    f = tmp_path / "q.jsonl"
    f.write_text("a\nb\n")
    with pytest.raises(SystemExit):
        freshstream_cli.Freshstream().run(queries=str(f), limit=1, sample="bogus")
