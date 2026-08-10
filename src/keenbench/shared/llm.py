import json
import os
from typing import Any, Protocol

import httpx

MAX_ERROR_CHARS = 500
RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
DEFAULT_JUDGE_MODEL = "google/gemini-3-flash-preview"
DEFAULT_LLM_MODEL = "google/gemini-3.1-flash-lite"

NO_REASONING_EFFORTS = frozenset({"", "none", "minimal"})


def resolve_judge_model(explicit: str | None) -> str:
    return explicit or os.environ.get("KEENBENCH_JUDGE_MODEL") or DEFAULT_JUDGE_MODEL


def resolve_llm_model(explicit: str | None) -> str:
    return explicit or os.environ.get("KEENBENCH_LLM_MODEL") or DEFAULT_LLM_MODEL


class LLMClientError(Exception):
    def __init__(self, error_type: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(f"{error_type}: {message}")
        self.error_type = error_type
        self.message = message
        self.retryable = retryable


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
        if reasoning_effort not in NO_REASONING_EFFORTS:
            body["reasoning"] = {"effort": reasoning_effort}

        try:
            payload = await self._request(body)
        except LLMClientError as exc:
            return None, {"error_type": exc.error_type, "error_message": exc.message}

        try:
            choice = payload["choices"][0]
            content = choice["message"].get("content")
        except (KeyError, IndexError, TypeError):
            return None, {"error_type": "no_content", "error_message": "no choices in response"}
        if choice.get("finish_reason") == "length":
            return None, {
                "error_type": "truncated",
                "error_message": "response hit max_tokens before completing",
            }
        text = _content_to_text(content)
        if not text:
            return None, {"error_type": "no_content", "error_message": "empty content in response"}
        return text, None

    async def _request(self, body: dict[str, Any]) -> Any:
        try:
            resp = await self._http().post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
            )
        except httpx.HTTPError as exc:
            raise LLMClientError("transport", str(exc)[:MAX_ERROR_CHARS], retryable=True) from exc
        if resp.status_code != 200:
            raise LLMClientError(
                "http_error",
                f"{resp.status_code}: {resp.text[:MAX_ERROR_CHARS]}",
                retryable=resp.status_code in RETRYABLE_STATUSES,
            )
        try:
            payload = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMClientError("bad_json", str(exc)[:MAX_ERROR_CHARS]) from exc
        if isinstance(payload, dict) and payload.get("error"):
            raise LLMClientError("api_error", str(payload["error"])[:MAX_ERROR_CHARS])
        return payload
