import json
from typing import Any, Protocol

import httpx

MAX_ERROR_CHARS = 500

_NO_REASONING = frozenset({"", "none", "minimal"})


class LLMClient(Protocol):
    async def complete(
        self, prompt: str, *, max_tokens: int, reasoning_effort: str
    ) -> tuple[str | None, dict[str, str] | None]: ...


def _content_to_text(content: Any) -> str | None:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return None


class OpenRouterClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout_s: float = 60.0,
        temperature: float = 0.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.temperature = temperature
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_s)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def complete(
        self, prompt: str, *, max_tokens: int, reasoning_effort: str
    ) -> tuple[str | None, dict[str, str] | None]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": self.temperature,
        }
        if reasoning_effort not in _NO_REASONING:
            body["reasoning"] = {"effort": reasoning_effort}

        try:
            resp = await self._http().post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
            )
        except httpx.HTTPError as exc:
            return None, {"error_type": "transport", "error_message": str(exc)[:MAX_ERROR_CHARS]}

        if resp.status_code != 200:
            return None, {
                "error_type": "http_error",
                "error_message": f"{resp.status_code}: {resp.text[:MAX_ERROR_CHARS]}",
            }

        try:
            payload = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            return None, {"error_type": "bad_json", "error_message": str(exc)[:MAX_ERROR_CHARS]}

        if isinstance(payload, dict) and payload.get("error"):
            return None, {
                "error_type": "api_error",
                "error_message": str(payload["error"])[:MAX_ERROR_CHARS],
            }

        try:
            choice = payload["choices"][0]
            content = choice["message"].get("content")
        except (KeyError, IndexError, TypeError):
            return None, {"error_type": "no_content", "error_message": "no choices in response"}
        if isinstance(choice, dict) and choice.get("finish_reason") == "length":
            return None, {
                "error_type": "truncated",
                "error_message": "response hit max_tokens before completing",
            }
        text = _content_to_text(content)
        if not text:
            return None, {"error_type": "no_content", "error_message": "empty content in response"}
        return text, None
