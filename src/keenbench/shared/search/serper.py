from keenbench.shared.search.base import HttpSearchClient, SearchResult, serp_results


class SerperClient(HttpSearchClient):
    engine = "google"
    base_url = "https://google.serper.dev"

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/search",
            json={"q": query, "num": min(num_results, 100), "gl": "us", "hl": "en"},
            headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
        )
        if err is not None:
            return None, err
        results = serp_results(
            payload,
            kg_key="knowledgeGraph",
            ab_key="answerBox",
            organic_key="organic",
            num_results=num_results,
        )
        return results, None
