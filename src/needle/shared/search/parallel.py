from typing import Any

from needle.shared.search.base import HttpSearchClient, SearchResult
from needle.shared.search.queryops import parse_ops


class ParallelClient(HttpSearchClient):
    engine = "parallel"
    base_url = "https://api.parallel.ai"

    def __init__(self, *, api_key: str, mode: str = "basic", timeout_s: float = 60.0) -> None:
        super().__init__(api_key=api_key, timeout_s=timeout_s)
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
            )
            for r in raw_results[:num_results]
            if r.get("url")
        ]
        return results, None
