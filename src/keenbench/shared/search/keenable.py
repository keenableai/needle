from keenbench.shared.search.base import HttpSearchClient, SearchResult


class KeenableClient(HttpSearchClient):
    engine = "keenable"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.keenable.ai",
        mode: str = "pro",
        timeout_s: float = 30.0,
        max_concurrency: int = 8,
    ) -> None:
        super().__init__(timeout_s=timeout_s, max_concurrency=max_concurrency)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.mode = mode

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        headers = {"X-API-Key": self.api_key} if self.api_key else {}
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/v1/search",
            json={"query": query, "mode": self.mode},
            headers=headers,
        )
        if err is not None:
            return None, err
        raw_results = payload.get("results", []) if isinstance(payload, dict) else []
        results = [
            SearchResult(
                url=r["url"],
                title=r.get("title"),
                snippet=r.get("snippet") or r.get("description"),
                published_date=r.get("published_at"),
                raw=r,
            )
            for r in raw_results[:num_results]
            if r.get("url")
        ]
        return results, None
