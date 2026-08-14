import json

import httpx

from keenbench.shared.llm import OpenRouterClient


def _client(handler):
    client = OpenRouterClient(api_key="k", model="openai/gpt-5.6-terra")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


def _capture(seen, *, finish_reason="stop", content="hello"):
    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}, "finish_reason": finish_reason}]},
        )

    return handler


async def test_complete_sends_minimal_reasoning_effort():
    seen = {}
    client = _client(_capture(seen))
    text, err = await client.complete("p", max_tokens=256, reasoning_effort="minimal")
    assert err is None and text == "hello"
    assert seen["reasoning"] == {"effort": "minimal"}


async def test_complete_omits_reasoning_when_disabled():
    for effort in ("", "none"):
        seen = {}
        client = _client(_capture(seen))
        text, err = await client.complete("p", max_tokens=256, reasoning_effort=effort)
        assert err is None and text == "hello"
        assert "reasoning" not in seen


async def test_complete_passes_other_efforts_through():
    seen = {}
    client = _client(_capture(seen))
    await client.complete("p", max_tokens=256, reasoning_effort="high")
    assert seen["reasoning"] == {"effort": "high"}


async def test_complete_reports_truncation():
    seen = {}
    client = _client(_capture(seen, finish_reason="length"))
    text, err = await client.complete("p", max_tokens=8, reasoning_effort="minimal")
    assert text is None
    assert err["error_type"] == "truncated"
