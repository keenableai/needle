from needle.shared.search.base import HttpSearchClient, SearchResult, clamped_chars
from needle.shared.search.queryops import QueryOps, clipped_text, parse_ops

MAX_QUERY_CHARS = 1000
MAX_RESULTS = 50
MAX_CONTENT_CHARS = 3000


def _query(ops: QueryOps) -> str:
    suffix = " OR ".join(f"site:{s}" for s in ops.sites)
    budget = MAX_QUERY_CHARS - len(suffix) - 1
    return " ".join(p for p in (clipped_text(ops.text, max(budget, 0)), suffix) if p)


class WebIqClient(HttpSearchClient):
    engine = "webiq"
    base_url = "https://api.microsoft.ai"

    def __init__(self, *, api_key: str, snippet_chars: int = 0, timeout_s: float = 30.0) -> None:
        super().__init__(api_key=api_key, timeout_s=timeout_s)
        self.snippet_chars = snippet_chars

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/v3/search/web",
            json={
                "query": _query(parse_ops(query)),
                "maxResults": min(num_results, MAX_RESULTS),
                "language": "en",
                "region": "US",
                "contentFormat": "passage",
                "maxLength": clamped_chars(self.snippet_chars, 1, MAX_CONTENT_CHARS)
                or MAX_CONTENT_CHARS,
                "safeSearch": "off",
            },
            headers={"x-apikey": self.api_key},
        )
        if err is not None:
            return None, err
        raw = payload.get("webResults") if isinstance(payload, dict) else None
        results = [
            SearchResult(
                url=r["url"],
                title=r.get("title") or None,
                snippet=r.get("content") or None,
                published_date=r.get("lastUpdatedAt") or None,
            )
            for r in (raw if isinstance(raw, list) else [])
            if isinstance(r, dict) and r.get("url")
        ]
        return results[:num_results], None
