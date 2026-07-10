import asyncio

import pytest

from keenbench.shared.search import (
    BraveClient,
    ExaClient,
    KeenableClient,
    OctenClient,
    ParallelClient,
    PerplexityClient,
    SearchApiClient,
    SearchResult,
    SerperClient,
    TavilyClient,
    build_search_clients,
    latency_stats,
)


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


async def test_searchapi_maps_kg_answer_box_and_organic(monkeypatch):
    payload = {
        "knowledge_graph": {"website": "https://kg", "title": "KG", "description": "dk"},
        "answer_box": {"link": "https://ab", "title": "AB", "snippet": "sa"},
        "organic_results": [
            {"link": "https://a", "title": "A", "snippet": "so", "date": "Mar 3, 2026"},
            {"title": "no link"},
        ],
    }
    c = SearchApiClient(api_key="k", engine="google")
    fake, calls = _canned(payload)
    monkeypatch.setattr(c, "_request_json", fake)

    results, err = await c.search("hi", num_results=3)
    assert err is None
    assert [r.url for r in results] == ["https://kg", "https://ab", "https://a"]
    assert results[2].published_date == "Mar 3, 2026"
    assert calls["method"] == "GET"
    assert calls["params"] == {"q": "hi", "num": 3, "engine": "google", "gl": "us", "hl": "en"}
    assert calls["headers"] == {"Authorization": "Bearer k"}


def _no_results_http(message):
    class FakeResp:
        status_code = 200

        def json(self):
            return {"error": message}

    class FakeHttp:
        async def request(self, method, url, **kwargs):
            return FakeResp()

    return FakeHttp()


async def test_request_json_error_field(monkeypatch):
    c = SearchApiClient(api_key="k", engine="bing")
    monkeypatch.setattr(c, "_http", lambda: _no_results_http("invalid key"))
    results, err = await c.search("q")
    assert results is None
    assert err == {"error_type": "api_error", "error_message": "invalid key"}
    assert c.latencies_ms == []


@pytest.mark.parametrize(
    "query",
    [
        "acme site:sec.gov",
        'acme "annual report"',
        "acme “annual report” comments",
        "acme after:2026-01-01 before:2026-04-01",
    ],
)
async def test_searchapi_empty_results_exempt_for_operator_queries(monkeypatch, query):
    c = SearchApiClient(api_key="k", engine="google")
    monkeypatch.setattr(c, "_http", lambda: _no_results_http("Google didn't return any results."))
    results, err = await c.search(query)
    assert err is None
    assert results == []
    assert c.latencies_ms == []


async def test_searchapi_empty_results_still_error_for_plain_query(monkeypatch):
    c = SearchApiClient(api_key="k", engine="bing")
    monkeypatch.setattr(c, "_http", lambda: _no_results_http("Bing didn't return any results."))
    results, err = await c.search("acme annual report")
    assert results is None
    assert err == {"error_type": "api_error", "error_message": "Bing didn't return any results."}


async def test_searchapi_real_error_not_masked_by_operator(monkeypatch):
    c = SearchApiClient(api_key="k", engine="google")
    monkeypatch.setattr(c, "_http", lambda: _no_results_http("invalid api key"))
    results, err = await c.search("acme site:sec.gov")
    assert results is None
    assert err == {"error_type": "api_error", "error_message": "invalid api key"}


async def test_serper_maps_kg_answer_box_and_organic(monkeypatch):
    payload = {
        "knowledgeGraph": {"website": "https://kg", "title": "KG", "description": "dk"},
        "answerBox": {"link": "https://ab", "title": "AB", "snippet": "sa"},
        "organic": [
            {"link": "https://a", "title": "A", "snippet": "so", "date": "Mar 3, 2026"},
            {"title": "no link"},
        ],
    }
    c = SerperClient(api_key="k")
    fake, calls = _canned(payload)
    monkeypatch.setattr(c, "_request_json", fake)

    results, err = await c.search("hi", num_results=3)
    assert err is None
    assert [r.url for r in results] == ["https://kg", "https://ab", "https://a"]
    assert results[2].published_date == "Mar 3, 2026"
    assert calls["method"] == "POST"
    assert calls["url"] == "https://google.serper.dev/search"
    assert calls["json"] == {"q": "hi", "num": 3, "gl": "us", "hl": "en"}
    assert calls["headers"] == {"X-API-KEY": "k", "Content-Type": "application/json"}


async def test_serper_tolerates_malformed_payload(monkeypatch):
    payload = {
        "knowledgeGraph": "not a dict",
        "answerBox": ["not", "a", "dict"],
        "organic": [None, "junk", {"link": "https://a", "title": "A"}, 7],
    }
    c = SerperClient(api_key="k")
    fake, _ = _canned(payload)
    monkeypatch.setattr(c, "_request_json", fake)
    results, err = await c.search("hi")
    assert err is None
    assert [r.url for r in results] == ["https://a"]

    fake, _ = _canned({"organic": "not a list"})
    monkeypatch.setattr(c, "_request_json", fake)
    results, err = await c.search("hi")
    assert err is None
    assert results == []


async def test_serper_empty_results_not_an_error(monkeypatch):
    c = SerperClient(api_key="k")
    fake, _ = _canned({"organic": []})
    monkeypatch.setattr(c, "_request_json", fake)
    results, err = await c.search("acme annual report")
    assert err is None
    assert results == []


async def test_brave_maps_fields(monkeypatch):
    payload = {
        "web": {
            "results": [
                {
                    "url": "https://a",
                    "title": "A",
                    "description": "da",
                    "page_age": "2026-06-30T00:00:00",
                },
                {"title": "no url"},
            ]
        }
    }
    c = BraveClient(api_key="k")
    fake, calls = _canned(payload)
    monkeypatch.setattr(c, "_request_json", fake)

    results, err = await c.search("hi", num_results=30)
    assert err is None
    assert len(results) == 1
    assert results[0].snippet == "da"
    assert results[0].published_date == "2026-06-30T00:00:00"
    assert calls["params"]["count"] == 20
    assert calls["headers"]["X-Subscription-Token"] == "k"


async def test_parallel_joins_excerpts_and_builds_body(monkeypatch):
    payload = {"results": [{"url": "https://a", "title": "A", "excerpts": ["one", "two"]}]}
    c = ParallelClient(api_key="k")
    fake, calls = _canned(payload)
    monkeypatch.setattr(c, "_request_json", fake)

    results, err = await c.search("hi", num_results=5)
    assert err is None
    assert results[0].snippet == "one\ntwo"
    assert calls["json"] == {
        "search_queries": ["hi"],
        "mode": "basic",
        "advanced_settings": {"max_results": 5},
    }
    assert calls["headers"] == {"x-api-key": "k"}


async def test_tavily_maps_fields_and_builds_body(monkeypatch):
    payload = {
        "results": [
            {
                "url": "https://a",
                "title": "A",
                "content": "ca",
                "published_date": "2026-07-01",
                "score": 0.9,
            }
        ]
    }
    c = TavilyClient(api_key="k")
    fake, calls = _canned(payload)
    monkeypatch.setattr(c, "_request_json", fake)

    results, err = await c.search("hi", num_results=25)
    assert err is None
    assert results[0].snippet == "ca"
    assert results[0].published_date == "2026-07-01"
    assert results[0].score == 0.9
    assert calls["json"] == {"query": "hi", "max_results": 20, "search_depth": "basic"}
    assert calls["headers"] == {"Authorization": "Bearer k"}


async def test_octen_maps_fields_and_builds_body(monkeypatch):
    payload = {
        "data": {
            "query": "hi",
            "results": [
                {
                    "url": "https://a",
                    "title": "A",
                    "highlight": "ha",
                    "time_published": "2026-07-01T00:00:00Z",
                },
                {"url": "https://b", "title": "", "highlight": "", "time_published": ""},
                {"title": "no url"},
            ],
        },
        "code": 0,
        "msg": "success",
    }
    c = OctenClient(api_key="k")
    fake, calls = _canned(payload)
    monkeypatch.setattr(c, "_request_json", fake)

    results, err = await c.search("hi", num_results=5)
    assert err is None
    assert [r.url for r in results] == ["https://a", "https://b"]
    assert results[0].snippet == "ha"
    assert results[0].published_date == "2026-07-01T00:00:00Z"
    assert results[1].title is None
    assert results[1].snippet is None
    assert results[1].published_date is None
    assert calls["url"] == "https://api.octen.ai/search"
    assert calls["json"] == {
        "query": "hi",
        "count": 5,
        "highlight": {"enable": True, "max_tokens": 512},
    }
    assert calls["headers"] == {"X-Api-Key": "k"}


async def test_perplexity_maps_results_and_builds_body(monkeypatch):
    payload = {
        "results": [
            {"url": "https://a", "title": "A", "snippet": "sa", "date": "2026-07-01"},
            {"url": "https://b", "title": "B", "snippet": "sb"},
            {"title": "no url"},
        ],
        "id": "req-1",
    }
    c = PerplexityClient(api_key="k")
    fake, calls = _canned(payload)
    monkeypatch.setattr(c, "_request_json", fake)

    results, err = await c.search("hi", num_results=25)
    assert err is None
    assert [r.url for r in results] == ["https://a", "https://b"]
    assert results[0].snippet == "sa"
    assert results[0].published_date == "2026-07-01"
    assert calls["url"] == "https://api.perplexity.ai/search"
    assert calls["json"] == {
        "query": "hi",
        "max_results": 20,
        "search_context_size": "low",
    }
    assert calls["headers"] == {"Authorization": "Bearer k"}


def test_factory_builds_new_engines(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "gk")
    monkeypatch.setenv("SEARCHAPI_API_KEY", "sk")
    monkeypatch.setenv("BRAVE_API_KEY", "bk")
    monkeypatch.setenv("PARALLEL_API_KEY", "pk")
    monkeypatch.setenv("TAVILY_API_KEY", "tk")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "xk")
    monkeypatch.setenv("OCTEN_API_KEY", "ok")
    clients = build_search_clients(
        ["google", "bing", "brave", "parallel", "tavily", "perplexity", "octen"]
    )
    assert isinstance(clients["google"], SerperClient)
    assert clients["google"].engine == "google"
    assert clients["google"].api_key == "gk"
    assert clients["bing"].engine == "bing"
    assert clients["bing"].api_key == "sk"
    assert isinstance(clients["brave"], BraveClient)
    assert isinstance(clients["parallel"], ParallelClient)
    assert isinstance(clients["tavily"], TavilyClient)
    assert isinstance(clients["perplexity"], PerplexityClient)
    assert clients["perplexity"].api_key == "xk"
    assert isinstance(clients["octen"], OctenClient)
    assert clients["octen"].api_key == "ok"


def test_factory_requires_key(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="BRAVE_API_KEY"):
        build_search_clients(["brave"])


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
    assert KeenableClient()._sem._value == 1
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
    assert c.latencies_ms == []
    await c.aclose()
    assert c._client is None


async def test_latency_recorded_only_for_ok_responses(monkeypatch):
    class OkResp:
        status_code = 200

        def json(self):
            return {"results": []}

    class BadResp:
        status_code = 500
        text = "boom"

    responses = [OkResp(), BadResp(), OkResp()]

    class FakeHttp:
        async def request(self, method, url, **kwargs):
            return responses.pop(0)

    c = KeenableClient()
    monkeypatch.setattr(c, "_http", lambda: FakeHttp())
    for _ in range(3):
        await c.search("q")
    assert len(c.latencies_ms) == 2
    assert all(v >= 0 for v in c.latencies_ms)


def test_latency_stats():
    assert latency_stats([]) is None
    assert latency_stats([100.0]) == {
        "n": 1,
        "mean_ms": 100.0,
        "p50_ms": 100.0,
        "p95_ms": 100.0,
        "samples_ms": [100.0],
    }
    stats = latency_stats([float(v) for v in range(1, 101)])
    assert stats["n"] == 100
    assert stats["mean_ms"] == 50.5
    assert stats["p50_ms"] == 50.0
    assert stats["p95_ms"] == 95.0
