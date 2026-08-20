from typing import Any

from needle.shared.search.base import HttpSearchClient, SearchResult, clamped_chars
from needle.shared.search.queryops import parse_ops

MIN_SNIPPET_CHARS = 180
MAX_SNIPPET_CHARS = 10000


class KeenableClient(HttpSearchClient):
    engine = "keenable"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.keenable.ai",
        mode: str = "pro",
        app_title: str = "needle",
        snippet_chars: int = 0,
        timeout_s: float = 30.0,
    ) -> None:
        super().__init__(api_key=api_key, base_url=base_url, timeout_s=timeout_s)
        self.mode = mode
        self.app_title = app_title
        self.snippet_chars = snippet_chars

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        parts = [ops.text_with_sites()]
        if ops.after:
            parts.append(f"published_after:{ops.after.isoformat()}")
        if ops.before:
            parts.append(f"published_before:{ops.before.isoformat()}")
        query = " ".join(p for p in parts if p)
        headers = {"X-Keenable-Title": self.app_title}
        if self.api_key:
            path = "/v1/search"
            headers["X-API-Key"] = self.api_key
        else:
            path = "/v1/search/public"
        body: dict[str, Any] = {"query": query, "mode": self.mode}
        if (
            n := clamped_chars(self.snippet_chars, MIN_SNIPPET_CHARS, MAX_SNIPPET_CHARS)
        ) is not None:
            body["snippet_max_length"] = n
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}{path}",
            json=body,
            headers=headers,
        )
        if err is not None:
            return None, err
        raw_results = payload.get("results", []) if isinstance(payload, dict) else []
        results = [
            SearchResult(
                url=r["url"],
                title=r.get("title"),
                snippet=r.get("snippet") or r.get("description"),
                published_date=r.get("published_at"),
            )
            for r in raw_results[:num_results]
            if r.get("url")
        ]
        return results, None
