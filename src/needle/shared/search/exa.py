from typing import Any

from needle.shared.search.base import HttpSearchClient, SearchResult
from needle.shared.search.queryops import parse_ops


class ExaClient(HttpSearchClient):
    engine = "exa"
    base_url = "https://api.exa.ai"

    def __init__(
        self,
        *,
        api_key: str,
        search_type: str = "auto",
        include_text: bool = True,
        highlight_chars: int = 0,
        timeout_s: float = 30.0,
    ) -> None:
        super().__init__(api_key=api_key, timeout_s=timeout_s)
        self.search_type = search_type
        self.include_text = include_text
        self.highlight_chars = highlight_chars

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        body: dict[str, Any] = {
            "query": ops.text,
            "numResults": num_results,
            "type": self.search_type,
        }
        if ops.sites:
            body["includeDomains"] = list(ops.sites)
        if ops.after:
            body["startPublishedDate"] = f"{ops.after.isoformat()}T00:00:00.000Z"
        if ops.before:
            body["endPublishedDate"] = f"{ops.before.isoformat()}T23:59:59.999Z"
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
            )
            for r in raw_results[:num_results]
            if r.get("url")
        ]
        return results, None
