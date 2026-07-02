from keenbench.shared.search.base import MAX_ERROR_CHARS, HttpSearchClient, SearchResult


class SearchApiClient(HttpSearchClient):
    def __init__(
        self,
        *,
        api_key: str,
        engine: str,
        base_url: str = "https://www.searchapi.io/api/v1",
        country: str = "us",
        language: str = "en",
        timeout_s: float = 30.0,
        max_concurrency: int = 8,
    ) -> None:
        super().__init__(timeout_s=timeout_s, max_concurrency=max_concurrency)
        self.api_key = api_key
        self.engine = engine
        self.base_url = base_url.rstrip("/")
        self.country = country
        self.language = language

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        payload, err = await self._request_json(
            "GET",
            f"{self.base_url}/search",
            params={
                "q": query,
                "num": min(num_results, 100),
                "engine": self.engine,
                "gl": self.country,
                "hl": self.language,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
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

        results: list[SearchResult] = []
        kg = payload.get("knowledge_graph")
        if isinstance(kg, dict) and kg.get("website"):
            results.append(
                SearchResult(
                    url=kg["website"],
                    title=kg.get("title"),
                    snippet=kg.get("description"),
                    raw=kg,
                )
            )
        ab = payload.get("answer_box")
        if isinstance(ab, dict) and ab.get("link"):
            results.append(
                SearchResult(
                    url=ab["link"], title=ab.get("title"), snippet=ab.get("snippet"), raw=ab
                )
            )
        for r in payload.get("organic_results") or []:
            if not r.get("link"):
                continue
            results.append(
                SearchResult(
                    url=r["link"],
                    title=r.get("title"),
                    snippet=r.get("snippet"),
                    published_date=r.get("date"),
                    raw=r,
                )
            )
        return results[:num_results], None
