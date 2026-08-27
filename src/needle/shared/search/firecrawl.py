from datetime import date
from typing import Any

from needle.shared.search.base import HttpSearchClient, SearchResult
from needle.shared.search.queryops import parse_ops


def _tbs(after: date | None, before: date | None) -> str | None:
    if not (after or before):
        return None
    parts = ["cdr:1"]
    if after:
        parts.append(f"cd_min:{after.month}/{after.day}/{after.year}")
    if before:
        parts.append(f"cd_max:{before.month}/{before.day}/{before.year}")
    return ",".join(parts)


class FirecrawlClient(HttpSearchClient):
    engine = "firecrawl"
    base_url = "https://api.firecrawl.dev"

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        body: dict[str, Any] = {
            "query": ops.text_with_sites(),
            "limit": min(num_results, 100),
            "sources": ["web"],
        }
        tbs = _tbs(ops.after, ops.before)
        if tbs:
            body["tbs"] = tbs
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/v2/search",
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        if err is not None:
            return None, err
        data = payload.get("data") if isinstance(payload, dict) else None
        raw_results = data.get("web", []) if isinstance(data, dict) else []
        results = [
            SearchResult(url=r["url"], title=r.get("title"), snippet=r.get("description"))
            for r in raw_results[:num_results]
            if isinstance(r, dict) and r.get("url")
        ]
        return results, None
