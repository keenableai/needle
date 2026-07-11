from typing import Any

from keenbench.shared.search.base import HttpSearchClient, SearchResult
from keenbench.shared.search.queryops import parse_ops


class ParallelClient(HttpSearchClient):
    engine = "parallel"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.parallel.ai",
        mode: str = "basic",
        timeout_s: float = 60.0,
        max_concurrency: int = 8,
    ) -> None:
        super().__init__(timeout_s=timeout_s, max_concurrency=max_concurrency)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.mode = mode

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        advanced: dict[str, Any] = {"max_results": num_results}
        policy: dict[str, Any] = {}
        if ops.sites:
            policy["include_domains"] = list(ops.sites)
        if ops.after:
            policy["after_date"] = ops.after.isoformat()
        if policy:
            advanced["source_policy"] = policy
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/v1/search",
            error_field="error",
            json={
                "search_queries": [ops.text],
                "mode": self.mode,
                "advanced_settings": advanced,
            },
            headers={"x-api-key": self.api_key},
        )
        if err is not None:
            return None, err
        raw_results = payload.get("results", []) if isinstance(payload, dict) else []
        results = [
            SearchResult(
                url=r["url"],
                title=r.get("title"),
                snippet="\n".join(r.get("excerpts") or []) or None,
                raw=r,
            )
            for r in raw_results[:num_results]
            if r.get("url")
        ]
        return results, None
