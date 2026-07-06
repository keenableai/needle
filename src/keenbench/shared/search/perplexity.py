from keenbench.shared.search.base import HttpSearchClient, SearchResult


class PerplexityClient(HttpSearchClient):
    engine = "perplexity"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.perplexity.ai",
        model: str = "sonar",
        timeout_s: float = 60.0,
        max_concurrency: int = 4,
    ) -> None:
        super().__init__(timeout_s=timeout_s, max_concurrency=max_concurrency)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/chat/completions",
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": query}],
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        if err is not None:
            return None, err
        if not isinstance(payload, dict):
            payload = {}
        results = [
            SearchResult(
                url=r["url"],
                title=r.get("title"),
                snippet=r.get("snippet") or r.get("text"),
                published_date=r.get("date"),
                raw=r,
            )
            for r in payload.get("search_results") or []
            if isinstance(r, dict) and r.get("url")
        ]
        if not results:
            for c in payload.get("citations") or []:
                if isinstance(c, str) and c:
                    results.append(SearchResult(url=c, raw={"url": c}))
                elif isinstance(c, dict) and c.get("url"):
                    results.append(SearchResult(url=c["url"], title=c.get("title"), raw=c))
        return results[:num_results], None
