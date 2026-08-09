from typing import Any

from keenbench.shared.search.base import HttpSearchClient, SearchResult
from keenbench.shared.search.queryops import parse_ops


class TavilyClient(HttpSearchClient):
    engine = "tavily"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.tavily.com",
        search_depth: str = "basic",
        timeout_s: float = 30.0,
        max_concurrency: int = 1,
    ) -> None:
        super().__init__(timeout_s=timeout_s, max_concurrency=max_concurrency)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.search_depth = search_depth

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        body: dict[str, Any] = {
            "query": ops.text,
            "max_results": min(num_results, 20),
            "search_depth": self.search_depth,
        }
        if ops.sites:
            body["include_domains"] = list(ops.sites)
        if ops.after:
            body["start_date"] = ops.after.isoformat()
        if ops.before:
            body["end_date"] = ops.before.isoformat()
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/search",
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        if err is not None:
            return None, err
        raw_results = payload.get("results", []) if isinstance(payload, dict) else []
        results = [
            SearchResult(
                url=r["url"],
                title=r.get("title"),
                snippet=r.get("content"),
                published_date=r.get("published_date"),
                score=r.get("score"),
                raw=r,
            )
            for r in raw_results[:num_results]
            if r.get("url")
        ]
        return results, None
