import httpx
import pytest

import keenbench.shared.llm as llm_mod
from keenbench.shared.llm import LLMClientError, OpenRouterClient


def _client(handler) -> OpenRouterClient:
    client = OpenRouterClient(api_key="k", model="test/model")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


def _ok_payload() -> dict:
    return {
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


async def test_payload_5xx_error_is_retried(monkeypatch):
    monkeypatch.setattr(llm_mod, "RETRY_DELAY_S", 0.0)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                200, json={"error": {"message": "Internal Server Error", "code": 500}}
            )
        return httpx.Response(200, json=_ok_payload())

    client = _client(handler)
    result = await client.chat([{"role": "user", "content": "hi"}], max_tokens=10)
    assert result.content == "ok"
    assert calls["n"] == 2
    await client.aclose()


async def test_payload_4xx_error_is_not_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json={"error": {"message": "bad request", "code": 400}})

    client = _client(handler)
    with pytest.raises(LLMClientError, match="bad request"):
        await client.chat([{"role": "user", "content": "hi"}], max_tokens=10)
    assert calls["n"] == 1
    await client.aclose()
