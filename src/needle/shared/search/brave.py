from typing import Any

from needle.shared.search.base import HttpSearchClient, SearchResult
from needle.shared.search.queryops import freshness_window, parse_ops

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
    base_url = "https://api.search.brave.com/res/v1"

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
        if fresh := freshness_window(ops):
            params["freshness"] = fresh
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
            )
            for r in raw_results[:num_results]
            if r.get("url")
        ]
        return results, None
