from keenbench.shared.search.base import HttpSearchClient, SearchResult


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
        if not isinstance(payload, dict):
            payload = {}

        results: list[SearchResult] = []
        kg = payload.get("knowledgeGraph")
        if isinstance(kg, dict) and kg.get("website"):
            results.append(
                SearchResult(url=kg["website"], title=kg.get("title"), snippet=kg.get("description"))
            )
        ab = payload.get("answerBox")
        if isinstance(ab, dict) and ab.get("link"):
            results.append(
                SearchResult(url=ab["link"], title=ab.get("title"), snippet=ab.get("snippet"))
            )
        organic = payload.get("organic")
        for r in organic if isinstance(organic, list) else []:
            if not isinstance(r, dict) or not r.get("link"):
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
