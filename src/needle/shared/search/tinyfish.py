from typing import Any

from needle.shared.search.base import HttpSearchClient, SearchResult
from needle.shared.search.queryops import clipped_text, parse_ops

MAX_QUERY_CHARS = 2000


class TinyFishClient(HttpSearchClient):
    engine = "tinyfish"
    base_url = "https://api.search.tinyfish.ai"

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        params: dict[str, Any] = {"query": clipped_text(ops.text, MAX_QUERY_CHARS)}
        if ops.sites:
            params["include_domains"] = ",".join(ops.sites)
        if ops.after:
            params["after_date"] = ops.after.isoformat()
        if ops.before:
            params["before_date"] = ops.before.isoformat()
        payload, err = await self._request_json(
            "GET",
            self.base_url,
            params=params,
            headers={"X-API-Key": self.api_key},
        )
        if err is not None:
            return None, err
        raw_results = payload.get("results", []) if isinstance(payload, dict) else []
        results = [
            SearchResult(
                url=r["url"],
                title=r.get("title") or None,
                snippet=r.get("snippet") or None,
                published_date=r.get("date") or None,
            )
            for r in raw_results[:num_results]
            if isinstance(r, dict) and r.get("url")
        ]
        return results, None
