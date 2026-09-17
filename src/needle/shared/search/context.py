from datetime import UTC, datetime, timedelta
from typing import Any

from needle.shared.search.base import HttpSearchClient, SearchResult
from needle.shared.search.queryops import QueryOps, clipped_text, parse_ops

MAX_QUERY_CHARS = 500
MIN_NUM = 10
MAX_NUM = 100


def _freshness(ops: QueryOps, now: datetime | None = None) -> str | None:
    if ops.before or not ops.after:
        return None
    current = now or datetime.now(UTC)
    start = datetime(ops.after.year, ops.after.month, ops.after.day, tzinfo=UTC)
    if start > current:
        return None
    elapsed = current - start
    if elapsed <= timedelta(hours=24):
        return "last_24_hours"
    if elapsed <= timedelta(days=7):
        return "last_week"
    if elapsed <= timedelta(days=31):
        return "last_month"
    if elapsed <= timedelta(days=366):
        return "last_year"
    return None


class ContextDevClient(HttpSearchClient):
    engine = "context"
    base_url = "https://api.context.dev/v1"

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
        if fresh := _freshness(ops):
            body["freshness"] = fresh
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
