from keenbench.shared.search.base import MAX_ERROR_CHARS, HttpSearchClient, SearchResult


class ParallelClient(HttpSearchClient):
    engine = "parallel"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.parallel.ai",
        mode: str = "basic",
        timeout_s: float = 60.0,
        max_concurrency: int = 8,
    ) -> None:
        super().__init__(timeout_s=timeout_s, max_concurrency=max_concurrency)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.mode = mode

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/v1/search",
            json={
                "search_queries": [query],
                "mode": self.mode,
                "advanced_settings": {"max_results": num_results},
            },
            headers={"x-api-key": self.api_key},
        )
        if err is not None:
            return None, err
        if not isinstance(payload, dict):
            payload = {}
        if payload.get("error"):
            return None, {
                "error_type": "api_error",
                "error_message": str(payload["error"])[:MAX_ERROR_CHARS],
            }
        results = [
            SearchResult(
                url=r["url"],
                title=r.get("title"),
                snippet="\n".join(r.get("excerpts") or []) or None,
                raw=r,
            )
            for r in payload.get("results") or []
            if r.get("url")
        ]
        return results[:num_results], None
