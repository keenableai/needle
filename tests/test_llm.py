import json

import httpx

from needle.shared.llm import OpenRouterClient


def _capture(seen, *, finish_reason="stop", content="hello"):
    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}, "finish_reason": finish_reason}]},
        )

    return handler


async def _complete(handler, *, reasoning_effort, max_tokens=256, retry_base_s=None):
    client = OpenRouterClient(api_key="k", model="openai/gpt-5.6-terra")
    if retry_base_s is not None:
        client.retry_base_s = retry_base_s
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        return await client.complete("p", max_tokens=max_tokens, reasoning_effort=reasoning_effort)
    finally:
        await client.aclose()


def _sequence(*outcomes):
    calls = []

    def handler(request):
        calls.append(request)
        outcome = outcomes[min(len(calls) - 1, len(outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return handler, calls


def _ok_response():
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}]},
    )


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
    handler, calls = _sequence(httpx.Response(429, text="slow down"), _ok_response())
    text, err = await _complete(handler, reasoning_effort="", retry_base_s=0.0)
    assert err is None and text == "hello"
    assert len(calls) == 2


async def test_complete_reports_error_after_exhausted_retries():
    handler, calls = _sequence(httpx.Response(503, text="down"))
    text, err = await _complete(handler, reasoning_effort="", retry_base_s=0.0)
    assert text is None
    assert err["error_type"] == "http_error"
    assert len(calls) == OpenRouterClient.retry_attempts


async def test_complete_does_not_retry_non_retryable_status():
    handler, calls = _sequence(httpx.Response(400, text="bad request"))
    text, err = await _complete(handler, reasoning_effort="")
    assert text is None
    assert err["error_type"] == "http_error"
    assert len(calls) == 1


async def test_complete_does_not_retry_timeouts():
    handler, calls = _sequence(httpx.ReadTimeout("slow"))
    text, err = await _complete(handler, reasoning_effort="")
    assert text is None
    assert err["error_type"] == "transport"
    assert len(calls) == 1


async def test_complete_reports_truncation():
    seen = {}
    text, err = await _complete(
        _capture(seen, finish_reason="length"), reasoning_effort="minimal", max_tokens=8
    )
    assert text is None
    assert err["error_type"] == "truncated"
