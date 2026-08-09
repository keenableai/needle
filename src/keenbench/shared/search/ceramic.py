from typing import Any

from keenbench.shared.search.base import HttpSearchClient, SearchResult
from keenbench.shared.search.queryops import parse_ops

MAX_QUERY_WORDS = 50
MIN_DESCRIPTION_CHARS = 1000
MAX_DESCRIPTION_CHARS = 8000


class CeramicClient(HttpSearchClient):
    engine = "ceramic"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.ceramic.ai",
        description_chars: int = 0,
        timeout_s: float = 30.0,
        max_concurrency: int = 1,
    ) -> None:
        super().__init__(timeout_s=timeout_s, max_concurrency=max_concurrency)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.description_chars = description_chars

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        body: dict[str, Any] = {"query": " ".join(ops.text.split()[:MAX_QUERY_WORDS])}
        if self.description_chars > 0:
            body["maxDescriptionLength"] = min(
                max(self.description_chars, MIN_DESCRIPTION_CHARS), MAX_DESCRIPTION_CHARS
            )
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/search",
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        if err is not None:
            return None, err
        result = payload.get("result") if isinstance(payload, dict) else None
        raw_results = result.get("results", []) if isinstance(result, dict) else []
        results = [
            SearchResult(
                url=r["url"],
                title=r.get("title") or None,
                snippet=r.get("description") or None,
                raw=r,
            )
            for r in raw_results[:num_results]
            if r.get("url")
        ]
        return results, None
