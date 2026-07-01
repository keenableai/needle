import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

MAX_ERROR_CHARS = 500


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str | None = None
    snippet: str | None = None
    published_date: str | None = None
    score: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class SearchClient(Protocol):
    engine: str

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]: ...


class HttpSearchClient:
    engine: str = ""

    def __init__(self, *, timeout_s: float = 30.0, max_concurrency: int = 8) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self.timeout_s = timeout_s
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
        self, method: str, url: str, **kwargs: Any
    ) -> tuple[Any, dict[str, str] | None]:
        try:
            async with self._sem:
                resp = await self._http().request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            return None, {"error_type": "transport", "error_message": str(exc)[:MAX_ERROR_CHARS]}
        if resp.status_code != 200:
            return None, {
                "error_type": "http_error",
                "error_message": f"{resp.status_code}: {resp.text[:MAX_ERROR_CHARS]}",
            }
        try:
            return resp.json(), None
        except (json.JSONDecodeError, ValueError) as exc:
            return None, {"error_type": "bad_json", "error_message": str(exc)[:MAX_ERROR_CHARS]}
