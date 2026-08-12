from typing import Any

from keenbench.shared.search.base import HttpSearchClient, SearchResult
from keenbench.shared.search.queryops import parse_ops

MAX_QUERY_CHARS = 500


class OctenClient(HttpSearchClient):
    engine = "octen"
    base_url = "https://api.octen.ai"

    def __init__(
        self, *, api_key: str, highlight_max_tokens: int = 512, timeout_s: float = 30.0
    ) -> None:
        super().__init__(api_key=api_key, timeout_s=timeout_s)
        self.highlight_max_tokens = highlight_max_tokens

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        text = ops.text
        if len(text) > MAX_QUERY_CHARS:
            text = text[:MAX_QUERY_CHARS].rsplit(" ", 1)[0]
        body: dict[str, Any] = {
            "query": text,
            "count": num_results,
            "highlight": {"enable": True, "max_tokens": self.highlight_max_tokens},
        }
        if ops.sites:
            body["include_domains"] = list(ops.sites)
        if ops.after:
            body["start_time"] = f"{ops.after.isoformat()}T00:00:00Z"
        if ops.before:
            body["end_time"] = f"{ops.before.isoformat()}T23:59:59Z"
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/search",
            json=body,
            headers={"X-Api-Key": self.api_key},
        )
        if err is not None:
            return None, err
        data = payload.get("data") if isinstance(payload, dict) else None
        raw_results = data.get("results", []) if isinstance(data, dict) else []
        results = [
            SearchResult(
                url=r["url"],
                title=r.get("title") or None,
                snippet=r.get("highlight") or None,
                published_date=r.get("time_published") or None,
            )
            for r in raw_results[:num_results]
            if r.get("url")
        ]
        return results, None
