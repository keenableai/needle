import asyncio
import json
import math
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

MAX_ERROR_CHARS = 500
RETRY_ATTEMPTS = 3
RETRY_BASE_S = 1.0
RETRY_MAX_S = 30.0
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


def latency_stats(latencies_ms: list[float]) -> dict[str, float | int | list[float]] | None:
    if not latencies_ms:
        return None
    values = sorted(latencies_ms)

    def pct(p: float) -> float:
        return values[max(0, math.ceil(p * len(values)) - 1)]

    return {
        "n": len(values),
        "mean_ms": round(sum(values) / len(values), 1),
        "p50_ms": round(pct(0.5), 1),
        "p95_ms": round(pct(0.95), 1),
        "samples_ms": [round(v, 1) for v in values],
    }


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str | None = None
    snippet: str | None = None
    published_date: str | None = None
    score: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def capped_snippet(result: SearchResult, snippet_chars: int) -> str:
    snippet = result.snippet or ""
    return snippet[:snippet_chars] if snippet_chars > 0 else snippet


class SearchClient(Protocol):
    engine: str
    latencies_ms: list[float]

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]: ...

    async def aclose(self) -> None: ...


async def search_all(
    engines: dict[str, "SearchClient"], texts: list[str], *, num_results: int
) -> list[list[tuple[list[SearchResult] | None, dict[str, str] | None]]]:
    by_engine = []
    for client in engines.values():
        by_engine.append(
            await asyncio.gather(*[client.search(t, num_results=num_results) for t in texts])
        )
    return [list(t) for t in zip(*by_engine, strict=True)]


class HttpSearchClient:
    engine: str = ""

    def __init__(self, *, timeout_s: float = 30.0, max_concurrency: int = 8) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self.timeout_s = timeout_s
        self.latencies_ms: list[float] = []
        self._client: httpx.AsyncClient | None = None
        self._sem = asyncio.Semaphore(max_concurrency)

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_s)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request_json(
        self, method: str, url: str, *, error_field: str | None = None, **kwargs: Any
    ) -> tuple[Any, dict[str, str] | None]:
        err: dict[str, str] | None = None
        delay = RETRY_BASE_S
        for attempt in range(RETRY_ATTEMPTS):
            if attempt:
                await asyncio.sleep(delay)
                delay = min(delay * 2, RETRY_MAX_S)
            try:
                async with self._sem:
                    started = time.perf_counter()
                    resp = await self._http().request(method, url, **kwargs)
                    elapsed_ms = (time.perf_counter() - started) * 1000.0
            except httpx.HTTPError as exc:
                detail = str(exc)[:MAX_ERROR_CHARS]
                message = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
                err = {"error_type": "transport", "error_message": message}
                continue
            if resp.status_code in RETRYABLE_STATUSES:
                err = {
                    "error_type": "http_error",
                    "error_message": f"{resp.status_code}: {resp.text[:MAX_ERROR_CHARS]}",
                }
                retry_after = resp.headers.get("retry-after")
                if retry_after is not None:
                    try:
                        delay = min(max(float(retry_after), 0.0), RETRY_MAX_S)
                    except ValueError:
                        pass
                continue
            if resp.status_code != 200:
                return None, {
                    "error_type": "http_error",
                    "error_message": f"{resp.status_code}: {resp.text[:MAX_ERROR_CHARS]}",
                }
            try:
                payload = resp.json()
            except (json.JSONDecodeError, ValueError) as exc:
                return None, {
                    "error_type": "bad_json",
                    "error_message": str(exc)[:MAX_ERROR_CHARS],
                }
            if error_field and isinstance(payload, dict) and payload.get(error_field):
                return None, {
                    "error_type": "api_error",
                    "error_message": str(payload[error_field])[:MAX_ERROR_CHARS],
                }
            self.latencies_ms.append(elapsed_ms)
            return payload, None
        return None, err

    async def _get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str | None:
        try:
            async with self._sem:
                resp = await self._http().request(
                    "GET", url, params=params, headers=headers, follow_redirects=True
                )
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        return resp.text
