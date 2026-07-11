from typing import Any

from keenbench.shared.search.base import HttpSearchClient, SearchResult
from keenbench.shared.search.queryops import parse_ops


class PerplexityClient(HttpSearchClient):
    engine = "perplexity"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.perplexity.ai",
        timeout_s: float = 60.0,
        max_concurrency: int = 4,
    ) -> None:
        super().__init__(timeout_s=timeout_s, max_concurrency=max_concurrency)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        body: dict[str, Any] = {
            "query": ops.text,
            "max_results": min(num_results, 20),
            "search_context_size": "low",
        }
        if ops.sites:
            body["search_domain_filter"] = list(ops.sites)
        if ops.after:
            body["search_after_date_filter"] = ops.after_mdy()
        if ops.before:
            body["search_before_date_filter"] = ops.before_mdy()
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/search",
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        if err is not None:
            return None, err
        if not isinstance(payload, dict):
            payload = {}
        results = [
            SearchResult(
                url=r["url"],
                title=r.get("title"),
                snippet=r.get("snippet"),
                published_date=r.get("date"),
                raw=r,
            )
            for r in payload.get("results") or []
            if isinstance(r, dict) and r.get("url")
        ]
        return results[:num_results], None
