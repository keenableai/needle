from typing import Any

from keenbench.shared.search.base import EngineClient, SearchResult
from keenbench.shared.search.queryops import parse_ops

MAX_QUERY_CHARS = 500


class OctenClient(EngineClient):
    engine = "octen"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.octen.ai",
        highlight_max_tokens: int = 512,
        timeout_s: float = 30.0,
        max_concurrency: int | None = None,
    ) -> None:
        super().__init__(timeout_s=timeout_s, max_concurrency=max_concurrency)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
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
                raw=r,
            )
            for r in raw_results[:num_results]
            if r.get("url")
        ]
        return results, None
