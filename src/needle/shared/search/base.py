import asyncio
import json
import math
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from needle.shared.retry import (
    MAX_ERROR_CHARS,
    RETRY_ATTEMPTS,
    RETRY_BASE_S,
    send_with_retry,
)

USER_AGENT = "needle/0.1 (contact@keenable.ai)"


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


DEFAULT_SNIPPET_CHARS = 2000


def clamped_chars(requested: int, lo: int, hi: int) -> int | None:
    return min(max(requested, lo), hi) if requested > 0 else None


def capped_snippet(result: SearchResult, snippet_chars: int) -> str:
    snippet = result.snippet or ""
    return snippet[:snippet_chars] if snippet_chars > 0 else snippet


def titled_snippet(result: SearchResult, snippet_chars: int) -> str:
    return " ".join(p for p in (result.title, capped_snippet(result, snippet_chars)) if p)


def serp_results(
    payload: Any, *, kg_key: str, ab_key: str, organic_key: str, num_results: int
) -> list[SearchResult]:
    if not isinstance(payload, dict):
        payload = {}
    results: list[SearchResult] = []
    kg = payload.get(kg_key)
    if isinstance(kg, dict) and kg.get("website"):
        results.append(
            SearchResult(url=kg["website"], title=kg.get("title"), snippet=kg.get("description"))
        )
    ab = payload.get(ab_key)
    if isinstance(ab, dict) and ab.get("link"):
        results.append(
            SearchResult(url=ab["link"], title=ab.get("title"), snippet=ab.get("snippet"))
        )
    organic = payload.get(organic_key)
    for r in organic if isinstance(organic, list) else []:
        if not isinstance(r, dict) or not r.get("link"):
            continue
        results.append(
            SearchResult(
                url=r["link"],
                title=r.get("title"),
                snippet=r.get("snippet"),
                published_date=r.get("date"),
            )
        )
    return results[:num_results]


class SearchClient(Protocol):
    engine: str
    latencies_ms: list[float]

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]: ...

    async def aclose(self) -> None: ...


async def search_all(
    engines: dict[str, "SearchClient"],
    texts: list[str],
    *,
    num_results: int,
    concurrent_search: bool = False,
) -> list[list[tuple[list[SearchResult] | None, dict[str, str] | None]]]:
    if not concurrent_search:
        return [
            [await client.search(text, num_results=num_results) for client in engines.values()]
            for text in texts
        ]
    return list(
        await asyncio.gather(
            *[
                asyncio.gather(
                    *[client.search(text, num_results=num_results) for client in engines.values()]
                )
                for text in texts
            ]
        )
    )


class HttpSearchClient:
    engine: str = ""
    base_url: str = ""
    default_headers: dict[str, str] = {}
    retry_attempts: int = RETRY_ATTEMPTS
    retry_base_s: float = RETRY_BASE_S

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_s: float = 30.0,
        max_concurrency: int = 1,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self.api_key = api_key
        if base_url is not None:
            self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.latencies_ms: list[float] = []
        self._client: httpx.AsyncClient | None = None
        self._sem = asyncio.Semaphore(max_concurrency)

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_s, headers=self.default_headers)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _send(
        self, method: str, url: str, **kwargs: Any
    ) -> tuple[httpx.Response | None, float, dict[str, str] | None]:
        elapsed_ms = 0.0

        async def send() -> httpx.Response:
            nonlocal elapsed_ms
            async with self._sem:
                started = time.perf_counter()
                resp = await self._http().request(method, url, **kwargs)
                elapsed_ms = (time.perf_counter() - started) * 1000.0
            return resp

        resp, err = await send_with_retry(
            send, attempts=self.retry_attempts, base_s=self.retry_base_s
        )
        if resp is None:
            assert err is not None
            return None, 0.0, {"error_type": err[0], "error_message": err[1]}
        return resp, elapsed_ms, None

    async def _request_json(
        self, method: str, url: str, *, error_field: str | None = None, **kwargs: Any
    ) -> tuple[Any, dict[str, str] | None]:
        resp, elapsed_ms, err = await self._send(method, url, **kwargs)
        if resp is None:
            return None, err
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

    async def _get_text(self, url: str, *, params: dict[str, Any] | None = None) -> str | None:
        resp, _, _ = await self._send("GET", url, params=params, follow_redirects=True)
        if resp is None or resp.status_code != 200:
            return None
        return resp.text
