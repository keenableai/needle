from typing import Any

from needle.shared.search.base import HttpSearchClient, SearchResult
from needle.shared.search.queryops import clipped_text, parse_ops, recency

MAX_QUERY_CHARS = 500
MIN_NUM = 10
MAX_NUM = 100


class ContextDevClient(HttpSearchClient):
    engine = "context"
    base_url = "https://api.context.dev/v1"

    def __init__(
        self, *, api_key: str, description_chars: int = 0, timeout_s: float = 30.0
    ) -> None:
        super().__init__(api_key=api_key, timeout_s=timeout_s)
        self.description_chars = description_chars

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        body: dict[str, Any] = {
            "query": clipped_text(ops.text, MAX_QUERY_CHARS),
            "numResults": min(max(num_results, MIN_NUM), MAX_NUM),
            "country": "us",
            "queryFanout": False,
        }
        if ops.sites:
            body["includeDomains"] = list(ops.sites)
        if fresh := recency(ops):
            body["freshness"] = fresh
        if self.description_chars > 0:
            body["descriptionMaxCharacters"] = self.description_chars
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/web/search",
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        if err is not None:
            return None, err
        raw = payload.get("results") if isinstance(payload, dict) else None
        results = [
            SearchResult(
                url=r["url"],
                title=r.get("title") or None,
                snippet=r.get("description") or None,
            )
            for r in (raw if isinstance(raw, list) else [])
            if isinstance(r, dict) and r.get("url")
        ]
        return results[:num_results], None
