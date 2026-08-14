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


async def test_complete_reports_truncation():
    seen = {}
    text, err = await _complete(
        _capture(seen, finish_reason="length"), reasoning_effort="minimal", max_tokens=8
    )
    assert text is None
    assert err["error_type"] == "truncated"
