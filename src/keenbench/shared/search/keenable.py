from keenbench.shared.search.base import HttpSearchClient, SearchResult


class KeenableClient(HttpSearchClient):
    engine = "keenable"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.keenable.ai",
        mode: str = "pro",
        app_title: str = "keenbench",
        timeout_s: float = 30.0,
        max_concurrency: int | None = None,
    ) -> None:
        if max_concurrency is None:
            max_concurrency = 8 if api_key else 1
        super().__init__(timeout_s=timeout_s, max_concurrency=max_concurrency)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.mode = mode
        self.app_title = app_title

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        headers = {"X-Keenable-Title": self.app_title}
        if self.api_key:
            path = "/v1/search"
            headers["X-API-Key"] = self.api_key
        else:
            path = "/v1/search/public"
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}{path}",
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
