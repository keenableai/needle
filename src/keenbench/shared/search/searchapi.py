from keenbench.shared.search.base import HttpSearchClient, SearchResult


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
    def __init__(
        self,
        *,
        api_key: str,
        engine: str,
        base_url: str = "https://www.searchapi.io/api/v1",
        timeout_s: float = 30.0,
    ) -> None:
        super().__init__(api_key=api_key, base_url=base_url, timeout_s=timeout_s)
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
        if not isinstance(payload, dict):
            payload = {}

        results: list[SearchResult] = []
        kg = payload.get("knowledge_graph")
        if isinstance(kg, dict) and kg.get("website"):
            results.append(
                SearchResult(url=kg["website"], title=kg.get("title"), snippet=kg.get("description"))
            )
        ab = payload.get("answer_box")
        if isinstance(ab, dict) and ab.get("link"):
            results.append(
                SearchResult(url=ab["link"], title=ab.get("title"), snippet=ab.get("snippet"))
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
                )
            )
        return results[:num_results], None
