from typing import Any

from keenbench.shared.search.base import HttpSearchClient, SearchResult


class ExaClient(HttpSearchClient):
    engine = "exa"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.exa.ai",
        search_type: str = "auto",
        include_text: bool = True,
        highlight_chars: int = 0,
        timeout_s: float = 30.0,
        max_concurrency: int = 8,
    ) -> None:
        super().__init__(timeout_s=timeout_s, max_concurrency=max_concurrency)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.search_type = search_type
        self.include_text = include_text
        self.highlight_chars = highlight_chars

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        body: dict[str, Any] = {
            "query": query,
            "numResults": num_results,
            "type": self.search_type,
        }
        if self.highlight_chars > 0:
            body["contents"] = {"highlights": {"maxCharacters": self.highlight_chars}}
        elif self.include_text:
            body["contents"] = {"text": True}
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/search",
            json=body,
            headers={"x-api-key": self.api_key},
        )
        if err is not None:
            return None, err
        raw_results = payload.get("results", []) if isinstance(payload, dict) else []
        results = [
            SearchResult(
                url=r["url"],
                title=r.get("title"),
                snippet=r.get("text") or "\n".join(r.get("highlights") or []) or r.get("summary"),
                published_date=r.get("publishedDate"),
                score=r.get("score"),
                raw=r,
            )
            for r in raw_results[:num_results]
            if r.get("url")
        ]
        return results, None
