from typing import Any

from needle.shared.search.base import HttpSearchClient, SearchResult

MAX_NUM = 20


class JinaClient(HttpSearchClient):
    engine = "jina"
    base_url = "https://s.jina.ai"

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        payload, err = await self._request_json(
            "GET",
            f"{self.base_url}/",
            params={"q": query, "num": min(num_results, MAX_NUM)},
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "X-Respond-With": "no-content",
            },
        )
        if err is not None:
            return None, err
        raw: Any = payload.get("data") if isinstance(payload, dict) else None
        results = [
            SearchResult(
                url=r["url"],
                title=r.get("title") or None,
                snippet=r.get("description") or None,
                published_date=r.get("date") or None,
            )
            for r in (raw if isinstance(raw, list) else [])
            if isinstance(r, dict) and r.get("url")
        ]
        return results[:num_results], None
