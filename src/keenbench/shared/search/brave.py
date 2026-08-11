from datetime import UTC, date, datetime
from typing import Any

from keenbench.shared.search.base import HttpSearchClient, SearchResult
from keenbench.shared.search.queryops import parse_ops

EPOCH = date(1970, 1, 1)
MAX_QUERY_WORDS = 50
MAX_QUERY_CHARS = 400


def _clip_query(text: str, sites: tuple[str, ...]) -> str:
    site_terms = [f"site:{s}" for s in sites]
    words = text.split()[: max(MAX_QUERY_WORDS - len(site_terms), 0)]
    q = " ".join(words + site_terms)
    while words and len(q) > MAX_QUERY_CHARS:
        words.pop()
        q = " ".join(words + site_terms)
    return q


class BraveClient(HttpSearchClient):
    engine = "brave"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.search.brave.com/res/v1",
        timeout_s: float = 30.0,
    ) -> None:
        super().__init__(timeout_s=timeout_s)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        params: dict[str, Any] = {
            "q": _clip_query(ops.text, ops.sites),
            "count": min(num_results, 20),
            "country": "us",
            "search_lang": "en",
            "result_filter": "web",
        }
        if ops.after or ops.before:
            lo = ops.after or EPOCH
            hi = ops.before or datetime.now(UTC).date()
            params["freshness"] = f"{lo.isoformat()}to{hi.isoformat()}"
        payload, err = await self._request_json(
            "GET",
            f"{self.base_url}/web/search",
            params=params,
            headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
        )
        if err is not None:
            return None, err
        raw_results = payload.get("web", {}).get("results", []) if isinstance(payload, dict) else []
        results = [
            SearchResult(
                url=r["url"],
                title=r.get("title"),
                snippet=r.get("description"),
                published_date=r.get("page_age"),
                raw=r,
            )
            for r in raw_results[:num_results]
            if r.get("url")
        ]
        return results, None
