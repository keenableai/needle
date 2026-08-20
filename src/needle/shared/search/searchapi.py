from needle.shared.search.base import HttpSearchClient, SearchResult, serp_results


def _is_empty_results_error(err: dict[str, str]) -> bool:
    return (
        err.get("error_type") == "api_error"
        and "return any results" in err.get("error_message", "").lower()
    )


def _has_restrictive_operator(query: str) -> bool:
    lowered = query.lower()
    quotes = sum(query.count(c) for c in ('"', "“", "”"))
    return "site:" in lowered or "after:" in lowered or "before:" in lowered or quotes >= 2


class SearchApiClient(HttpSearchClient):
    base_url = "https://www.searchapi.io/api/v1"

    def __init__(self, *, api_key: str, engine: str, timeout_s: float = 30.0) -> None:
        super().__init__(api_key=api_key, timeout_s=timeout_s)
        self.engine = engine

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        payload, err = await self._request_json(
            "GET",
            f"{self.base_url}/search",
            error_field="error",
            params={
                "q": query,
                "num": min(num_results, 50),
                "engine": self.engine,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        if err is not None:
            if _is_empty_results_error(err) and _has_restrictive_operator(query):
                return [], None
            return None, err
        results = serp_results(
            payload,
            kg_key="knowledge_graph",
            ab_key="answer_box",
            organic_key="organic_results",
            num_results=num_results,
        )
        return results, None
