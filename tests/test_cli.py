import pytest

from keenbench.freshstream.cli import Freshstream
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
