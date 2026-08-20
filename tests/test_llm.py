import json

import httpx

from keenbench.shared.llm import OpenRouterClient


def _capture(seen, *, finish_reason="stop", content="hello"):
    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}, "finish_reason": finish_reason}]},
        )

    return handler


async def _complete(handler, *, reasoning_effort, max_tokens=256):
    client = OpenRouterClient(api_key="k", model="openai/gpt-5.6-terra")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        return await client.complete("p", max_tokens=max_tokens, reasoning_effort=reasoning_effort)
    finally:
        await client.aclose()


async def test_complete_sends_minimal_reasoning_effort():
    seen = {}
    text, err = await _complete(_capture(seen), reasoning_effort="minimal")
    assert err is None and text == "hello"
    assert seen["reasoning"] == {"effort": "minimal"}


async def test_complete_omits_reasoning_when_disabled():
    for effort in ("", "none"):
        seen = {}
        text, err = await _complete(_capture(seen), reasoning_effort=effort)
        assert err is None and text == "hello"
        assert "reasoning" not in seen


async def test_complete_passes_other_efforts_through():
    seen = {}
    await _complete(_capture(seen), reasoning_effort="high")
    assert seen["reasoning"] == {"effort": "high"}


async def test_complete_retries_retryable_status_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, text="slow down")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}]},
        )

    client = OpenRouterClient(api_key="k", model="openai/gpt-5.6-terra")
    client.retry_base_s = 0.0
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        text, err = await client.complete("p", max_tokens=8, reasoning_effort="")
    finally:
        await client.aclose()
    assert err is None and text == "hello"
    assert calls["n"] == 2


async def test_complete_reports_error_after_exhausted_retries():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503, text="down")

    client = OpenRouterClient(api_key="k", model="openai/gpt-5.6-terra")
    client.retry_base_s = 0.0
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        text, err = await client.complete("p", max_tokens=8, reasoning_effort="")
    finally:
        await client.aclose()
    assert text is None
    assert err["error_type"] == "http_error"
    assert calls["n"] == client.retry_attempts


async def test_complete_does_not_retry_non_retryable_status():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(400, text="bad request")

    client = OpenRouterClient(api_key="k", model="openai/gpt-5.6-terra")
    client.retry_base_s = 0.0
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        text, err = await client.complete("p", max_tokens=8, reasoning_effort="")
    finally:
        await client.aclose()
    assert text is None
    assert err["error_type"] == "http_error"
    assert calls["n"] == 1


async def test_complete_reports_truncation():
    seen = {}
    text, err = await _complete(
        _capture(seen, finish_reason="length"), reasoning_effort="minimal", max_tokens=8
    )
    assert text is None
    assert err["error_type"] == "truncated"
