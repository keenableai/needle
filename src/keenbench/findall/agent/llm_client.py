import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
AZURE_ANTHROPIC_MODELS = ("claude",)

DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.0
DEFAULT_SEED = 42
DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT_S = 180.0
MAX_RETRY_DELAY = 120.0
RATE_LIMIT_TERMINAL_THRESHOLD = 300.0

ANTHROPIC_STOP_REASON_MAP = {
    "end_turn": "stop",
    "max_tokens": "length",
    "stop_sequence": "stop",
    "tool_use": "tool_calls",
}


class LLMClientError(Exception):
    pass


class RateLimitError(LLMClientError):
    pass


class RetryableError(LLMClientError):
    def __init__(self, *args: Any, retry_after: float | None = None) -> None:
        super().__init__(*args)
        self.retry_after = retry_after


class LLMBackend(StrEnum):
    OPENROUTER = "openrouter"
    AZURE = "azure"


@dataclass
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class LLMResponse:
    content: str
    usage: LLMUsage = field(default_factory=LLMUsage)
    tool_calls: list[dict[str, Any]] | None = None
    finish_reason: str = "stop"


@dataclass(frozen=True)
class LLMConfig:
    model_id: str = "anthropic/claude-sonnet-4.5"
    backend: LLMBackend = LLMBackend.OPENROUTER
    provider: str | None = None


def is_anthropic_model(model: str) -> bool:
    return any(k in model.lower() for k in AZURE_ANTHROPIC_MODELS)


def _bearer_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


class LLMClient(ABC):
    backend: LLMBackend
    api_url: str
    api_key: str
    headers: dict[str, str]
    provider: str | None

    def __init__(
        self,
        *,
        model: str,
        timeout: float = DEFAULT_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
        seed: int = DEFAULT_SEED,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.seed = seed
        self._owns_client = http_client is None
        self.http_client = http_client or httpx.AsyncClient(timeout=timeout)
        self.total_usage = LLMUsage()
        self.retrying = AsyncRetrying(
            retry=retry_if_exception_type(RetryableError),
            stop=stop_after_attempt(max_retries),
            wait=self._retry_wait,
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        if not self.api_key:
            logger.warning("%s API key not configured", self.backend)

    async def aclose(self) -> None:
        if self._owns_client:
            await self.http_client.aclose()

    @abstractmethod
    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        *,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]: ...

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        if not data.get("choices"):
            raise LLMClientError(f"No response content from {self.backend}")
        content = None
        tool_calls = None
        finish_reason = "stop"
        for choice in data["choices"]:
            finish_reason = choice.get("finish_reason") or "stop"
            message = choice.get("message", {})
            if message.get("content"):
                content = message["content"]
            if message.get("tool_calls"):
                tool_calls = message["tool_calls"]
            if content or tool_calls:
                break
        if not content and not tool_calls:
            raise LLMClientError(f"Empty response content from {self.backend}")
        usage_data = data.get("usage", {}) or {}
        prompt_details = usage_data.get("prompt_tokens_details", {}) or {}
        return LLMResponse(
            content=(content or "").strip(),
            usage=LLMUsage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
                cache_read_tokens=prompt_details.get("cached_tokens", 0) or 0,
                cache_write_tokens=prompt_details.get("cache_write_tokens", 0) or 0,
            ),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: float | None = None,
    ) -> LLMResponse:
        if not self.api_key:
            raise LLMClientError(f"{self.backend} API key not configured")
        payload = self._build_payload(
            messages,
            tools,
            max_tokens=max_tokens if max_tokens is not None else self.max_tokens,
            temperature=temperature if temperature is not None else self.temperature,
        )
        response: LLMResponse = await self.retrying(self._attempt, payload, timeout or self.timeout)
        self._accumulate_usage(response.usage)
        return response

    async def complete(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        return await self.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )

    def _accumulate_usage(self, usage: LLMUsage) -> None:
        self.total_usage.prompt_tokens += usage.prompt_tokens
        self.total_usage.completion_tokens += usage.completion_tokens
        self.total_usage.total_tokens += usage.total_tokens
        self.total_usage.cache_read_tokens += usage.cache_read_tokens
        self.total_usage.cache_write_tokens += usage.cache_write_tokens

    def _rate_limit_wait(self, response: httpx.Response) -> float | None:
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return None
        try:
            raw_wait = float(retry_after)
        except ValueError:
            return None
        if raw_wait > RATE_LIMIT_TERMINAL_THRESHOLD:
            raise RateLimitError(
                f"Rate limit backoff ({raw_wait:.0f}s) exceeds terminal threshold "
                f"of {RATE_LIMIT_TERMINAL_THRESHOLD:.0f}s"
            )
        return min(raw_wait, MAX_RETRY_DELAY)

    def _error_message(self, exc: Exception) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            text = exc.response.text
            try:
                text = exc.response.json().get("error", {}).get("message", text)
            except (ValueError, AttributeError):
                pass
            return f"{self.backend} API error {exc.response.status_code}: {text}"
        if isinstance(exc, httpx.TimeoutException):
            return f"{self.backend} request timed out"
        if isinstance(exc, httpx.RequestError):
            return f"Failed to connect to {self.backend}: {exc}"
        return f"{self.backend} error: {exc}"

    async def _attempt(self, payload: dict[str, Any], timeout: float) -> LLMResponse:
        try:
            response = await self.http_client.post(
                self.api_url, headers=self.headers, json=payload, timeout=timeout
            )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise RetryableError(self._error_message(exc)) from exc
        if response.status_code == 429:
            wait = self._rate_limit_wait(response)
            raise RetryableError(f"Rate limited by {self.backend}", retry_after=wait)
        try:
            response.raise_for_status()
            return self._parse_response(response.json())
        except json.JSONDecodeError as exc:
            raise RetryableError(self._error_message(exc)) from exc
        except httpx.HTTPStatusError as exc:
            raise RetryableError(self._error_message(exc)) from exc

    def _retry_wait(self, retry_state: Any) -> float:
        exc = retry_state.outcome.exception()
        if isinstance(exc, RetryableError) and exc.retry_after is not None:
            return exc.retry_after
        return wait_random_exponential(multiplier=1.0, max=MAX_RETRY_DELAY)(retry_state)


class OpenRouterClient(LLMClient):
    backend = LLMBackend.OPENROUTER

    def __init__(self, *, api_key: str, provider: str | None = None, **common: Any) -> None:
        self.api_url = OPENROUTER_URL
        self.api_key = api_key
        self.provider = provider
        self.headers = _bearer_headers(api_key) | {
            "HTTP-Referer": "https://keenbench.keenable.ai",
            "X-Title": "Keenbench findall",
        }
        super().__init__(**common)

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        *,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "seed": self.seed,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if self.provider:
            payload["provider"] = {"order": [self.provider], "allow_fallbacks": False}
        if tools:
            payload["tools"] = tools
        return payload


class AzureOpenAIClient(LLMClient):
    backend = LLMBackend.AZURE

    def __init__(self, *, endpoint: str, api_key: str, **common: Any) -> None:
        self.api_url = endpoint.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.provider = None
        self.headers = _bearer_headers(api_key)
        super().__init__(**common)

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        *,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_completion_tokens": max_tokens,
            "messages": messages,
        }
        if temperature != DEFAULT_TEMPERATURE:
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = tools
        return payload


class AzureAnthropicClient(LLMClient):
    backend = LLMBackend.AZURE

    def __init__(self, *, endpoint: str, api_key: str, **common: Any) -> None:
        base = endpoint.rstrip("/").removesuffix("/v1/messages")
        self.api_url = base + "/v1/messages"
        self.api_key = api_key
        self.provider = None
        self.headers = _bearer_headers(api_key) | {"anthropic-version": "2023-06-01"}
        super().__init__(**common)

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        *,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        system_parts: list[str] = []
        filtered: list[dict[str, Any]] = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                system_parts.append(str(m.get("content", "")))
            elif role == "assistant" and m.get("tool_calls"):
                blocks: list[dict[str, Any]] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m["tool_calls"]:
                    fn = tc.get("function", {})
                    args_raw = fn.get("arguments", "{}")
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.get("id", ""),
                            "name": fn.get("name", ""),
                            "input": json.loads(args_raw)
                            if isinstance(args_raw, str)
                            else args_raw,
                        }
                    )
                filtered.append({"role": "assistant", "content": blocks})
            elif role == "tool":
                filtered.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.get("tool_call_id", ""),
                                "content": m.get("content", ""),
                            }
                        ],
                    }
                )
            else:
                filtered.append({"role": role, "content": m.get("content", "")})
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": filtered,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if temperature != DEFAULT_TEMPERATURE:
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = [
                {
                    "name": (fn := t.get("function", t)).get("name", ""),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {}),
                }
                for t in tools
            ]
        return payload

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        if data.get("type") == "error":
            err = data.get("error", {})
            raise LLMClientError(
                f"{self.backend} error: {err.get('type', 'unknown')}: {err.get('message', '')}"
            )
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    {
                        "id": block.get("id"),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    }
                )
        content = "\n".join(text_parts).strip()
        if not content and not tool_calls:
            raise LLMClientError(
                f"Empty response from {self.backend} (stop_reason={data.get('stop_reason')})"
            )
        usage_data = data.get("usage", {}) or {}
        input_tokens = usage_data.get("input_tokens", 0)
        output_tokens = usage_data.get("output_tokens", 0)
        stop_reason = data.get("stop_reason", "end_turn") or "end_turn"
        return LLMResponse(
            content=content,
            usage=LLMUsage(
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                cache_read_tokens=usage_data.get("cache_read_input_tokens", 0),
                cache_write_tokens=usage_data.get("cache_creation_input_tokens", 0),
            ),
            tool_calls=tool_calls or None,
            finish_reason=ANTHROPIC_STOP_REASON_MAP.get(stop_reason, stop_reason),
        )


def create_llm_client(
    llm_config: LLMConfig | None = None,
    *,
    api_key: str | None = None,
    model: str | None = None,
    backend: str | None = None,
    provider: str | None = None,
    **common: Any,
) -> LLMClient:
    cfg = llm_config or LLMConfig(
        model_id=model or "anthropic/claude-sonnet-4.5",
        backend=LLMBackend(backend or LLMBackend.OPENROUTER),
        provider=provider,
    )
    common["model"] = cfg.model_id
    if cfg.backend == LLMBackend.AZURE:
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        key = api_key or os.environ.get("AZURE_OPENAI_API_KEY", "")
        if not endpoint:
            raise LLMClientError(
                f"No Azure endpoint for model {cfg.model_id!r}. Set AZURE_OPENAI_ENDPOINT."
            )
        impl = AzureAnthropicClient if is_anthropic_model(cfg.model_id) else AzureOpenAIClient
        return impl(endpoint=endpoint, api_key=key, **common)
    return OpenRouterClient(
        api_key=api_key or os.environ.get("OPENROUTER_API_KEY", ""),
        provider=cfg.provider,
        **common,
    )
