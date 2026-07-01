import pytest

from keenbench.freshstream.cli import Freshstream
from keenbench.rankeval import cli as rankeval_cli
from keenbench.shared.llm import OpenRouterClient, _content_to_text


def test_run_rejects_unsupported_source():
    with pytest.raises(SystemExit):
        Freshstream().run(source="bogus")


def test_trending_rejects_rss_only_flags():
    with pytest.raises(SystemExit):
        Freshstream().run(source="trending", feeds="x.toml")


def test_rss_rejects_trends_only_flags():
    with pytest.raises(SystemExit):
        Freshstream().run(source="rss", max_trends=5)


def test_run_rejects_bad_feeds_file(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    with pytest.raises(SystemExit):
        Freshstream().run(feeds=str(tmp_path / "does-not-exist.toml"))


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


def test_rankeval_passes_keenable_api_key(monkeypatch, tmp_path):
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

    monkeypatch.setattr(rankeval_cli, "KeenableClient", FakeKeenable)
    monkeypatch.setattr(rankeval_cli, "run_rbp", fake_run_rbp)
    rankeval_cli.Rankeval().run(
        queries=str(qfile), engines="keenable", out=str(tmp_path / "r.json")
    )
    assert created == {"api_key": "kb-key", "mode": "pro"}
