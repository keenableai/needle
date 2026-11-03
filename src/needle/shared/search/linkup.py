import html
from typing import Any

from needle.shared.search.base import HttpSearchClient, SearchResult
from needle.shared.search.queryops import parse_ops


class LinkupClient(HttpSearchClient):
    engine = "linkup"
    base_url = "https://api.linkup.so"

    def __init__(self, *, api_key: str, depth: str = "standard", timeout_s: float = 30.0) -> None:
        super().__init__(api_key=api_key, timeout_s=timeout_s)
        self.depth = depth

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        body: dict[str, Any] = {
            "q": ops.text,
            "depth": self.depth,
            "outputType": "searchResults",
            "maxResults": num_results,
        }
        if ops.sites:
            body["includeDomains"] = list(ops.sites)[:100]
        if ops.after:
            body["fromDate"] = ops.after.isoformat()
        if ops.before:
            body["toDate"] = ops.before.isoformat()
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/v1/search",
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        if err is not None:
            return None, err
        raw_results = payload.get("results", []) if isinstance(payload, dict) else []
        results = [
            SearchResult(
                url=r["url"],
                title=html.unescape(r["name"]) if r.get("name") else None,
                snippet=html.unescape(r["content"]) if r.get("content") else None,
            )
            for r in raw_results
            if r.get("url") and r.get("type", "text") == "text"
        ]
        return results[:num_results], None
