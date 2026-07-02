import asyncio

import pytest

from keenbench.shared.search import ExaClient, KeenableClient, SearchResult


def _canned(payload):
    calls = {}

    async def fake(method, url, **kwargs):
        calls["method"] = method
        calls["url"] = url
        calls.update(kwargs)
        return payload, None

    return fake, calls


def test_search_result_defaults():
    r = SearchResult(url="https://ex.com")
    assert r.title is None and r.score is None and r.raw == {}


async def test_keenable_maps_fields_and_truncates(monkeypatch):
    payload = {
        "results": [
            {"url": "https://a", "title": "A", "snippet": "sa", "published_at": "2026-07-01"},
            {"url": "https://b", "title": "B", "description": "db"},
            {"title": "no url"},
        ]
    }
    c = KeenableClient()
    fake, calls = _canned(payload)
    monkeypatch.setattr(c, "_request_json", fake)

    results, err = await c.search("hello", num_results=1)
    assert err is None
    assert len(results) == 1
    assert results[0].url == "https://a"
    assert results[0].snippet == "sa"
    assert results[0].published_date == "2026-07-01"
    assert calls["url"].endswith("/v1/search/public")
    assert calls["json"] == {"query": "hello", "mode": "pro"}
    assert calls["headers"] == {"X-Keenable-Title": "keenbench"}


async def test_keenable_snippet_falls_back_to_description(monkeypatch):
    c = KeenableClient(api_key="k")
    fake, calls = _canned({"results": [{"url": "https://b", "description": "db"}]})
    monkeypatch.setattr(c, "_request_json", fake)
    results, _ = await c.search("q")
    assert results[0].snippet == "db"
    assert calls["url"].endswith("/v1/search")
    assert calls["headers"] == {"X-Keenable-Title": "keenbench", "X-API-Key": "k"}


async def test_exa_maps_fields_and_builds_body(monkeypatch):
    payload = {
        "results": [
            {
                "url": "https://a",
                "title": "A",
                "text": "body",
                "publishedDate": "2023-01-01",
                "score": 0.42,
            },
        ]
    }
    c = ExaClient(api_key="x")
    fake, calls = _canned(payload)
    monkeypatch.setattr(c, "_request_json", fake)

    results, err = await c.search("hi", num_results=5)
    assert err is None
    assert results[0].url == "https://a"
    assert results[0].snippet == "body"
    assert results[0].published_date == "2023-01-01"
    assert results[0].score == 0.42
    assert calls["json"] == {
        "query": "hi",
        "numResults": 5,
        "type": "auto",
        "contents": {"text": True},
    }
    assert calls["headers"] == {"x-api-key": "x"}


async def test_exa_omits_contents_when_text_disabled(monkeypatch):
    c = ExaClient(api_key="x", include_text=False)
    fake, calls = _canned({"results": []})
    monkeypatch.setattr(c, "_request_json", fake)
    await c.search("hi")
    assert "contents" not in calls["json"]


async def test_exa_highlights_mode(monkeypatch):
    c = ExaClient(api_key="x", highlight_chars=500)
    payload = {"results": [{"url": "https://a", "highlights": ["one", "two"]}]}
    fake, calls = _canned(payload)
    monkeypatch.setattr(c, "_request_json", fake)
    results, err = await c.search("hi")
    assert calls["json"]["contents"] == {"highlights": {"maxCharacters": 500}}
    assert results[0].snippet == "one\ntwo"


async def test_error_passthrough(monkeypatch):
    c = ExaClient(api_key="x")

    async def fail(method, url, **kwargs):
        return None, {"error_type": "http_error", "error_message": "401"}

    monkeypatch.setattr(c, "_request_json", fail)
    results, err = await c.search("q")
    assert results is None
    assert err == {"error_type": "http_error", "error_message": "401"}


def test_rejects_zero_max_concurrency():
    with pytest.raises(ValueError):
        KeenableClient(max_concurrency=0)


def test_keenable_keyless_defaults_to_low_concurrency():
    assert KeenableClient()._sem._value == 2
    assert KeenableClient(api_key="k")._sem._value == 8
    assert KeenableClient(max_concurrency=5)._sem._value == 5


async def test_max_concurrency_caps_in_flight(monkeypatch):
    active = 0
    peak = 0

    class FakeResp:
        status_code = 200

        def json(self):
            return {"results": []}

    class FakeHttp:
        async def request(self, method, url, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1
            return FakeResp()

    c = KeenableClient(max_concurrency=2)
    monkeypatch.setattr(c, "_http", lambda: FakeHttp())
    await asyncio.gather(*[c.search("q") for _ in range(6)])
    assert peak <= 2


async def test_real_http_path_errors_as_data_and_reuse_and_close():
    c = KeenableClient(base_url="http://127.0.0.1:1", timeout_s=2.0)
    r1, e1 = await c.search("q")
    client_after = c._client
    r2, e2 = await c.search("q")
    assert r1 is None and e1["error_type"] == "transport"
    assert r2 is None and e2["error_type"] == "transport"
    assert c._client is client_after and c._client is not None
    await c.aclose()
    assert c._client is None
