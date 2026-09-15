from typing import Any

from needle.shared.search.base import HttpSearchClient, SearchResult

MAX_NUM = 20


class JinaClient(HttpSearchClient):
    engine = "jina"
    base_url = "https://s.jina.ai"

    def __init__(self, *, api_key: str, snippet_chars: int = 0, timeout_s: float = 60.0) -> None:
        super().__init__(api_key=api_key, timeout_s=timeout_s)
        self.snippet_chars = snippet_chars

    def _snippet(self, r: dict[str, Any]) -> str | None:
        content = r.get("content") or ""
        if self.snippet_chars > 0:
            content = content[: self.snippet_chars]
        return content or r.get("description") or None

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        payload, err = await self._request_json(
            "GET",
            f"{self.base_url}/",
            params={"q": query, "num": min(num_results, MAX_NUM)},
            headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
        )
        if err is not None:
            return None, err
        raw: Any = payload.get("data") if isinstance(payload, dict) else None
        results = [
            SearchResult(
                url=r["url"],
                title=r.get("title") or None,
                snippet=self._snippet(r),
                published_date=r.get("publishedTime") or r.get("date") or None,
            )
            for r in (raw if isinstance(raw, list) else [])
            if isinstance(r, dict) and r.get("url")
        ]
        return results[:num_results], None
