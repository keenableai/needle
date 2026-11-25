from typing import Any

from needle.shared.search.base import HttpSearchClient, SearchResult
from needle.shared.search.context import _freshness
from needle.shared.search.queryops import clipped_text, parse_ops

MAX_QUERY_CHARS = 500
MAX_RESULTS = 50
MAX_DOMAINS = 20
TIME_RANGES = {
    "last_24_hours": "day",
    "last_week": "week",
    "last_month": "month",
    "last_year": "year",
}


class ClawifiClient(HttpSearchClient):
    engine = "clawifi"
    base_url = "https://api.clawifi.dev"

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        body: dict[str, Any] = {
            "query": clipped_text(ops.text, MAX_QUERY_CHARS),
            "max_results": min(max(num_results, 1), MAX_RESULTS),
        }
        if ops.sites:
            body["include_domains"] = list(ops.sites[:MAX_DOMAINS])
        if time_range := TIME_RANGES.get(_freshness(ops) or ""):
            body["time_range"] = time_range
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/search/free",
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
                snippet=r.get("snippet") or None,
                published_date=r.get("published_at") or None,
            )
            for r in (raw if isinstance(raw, list) else [])
            if isinstance(r, dict) and r.get("url")
        ]
        return results[:num_results], None
