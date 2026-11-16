import re
from typing import Any

from needle.shared.search.base import HttpSearchClient, SearchResult, clamped_chars
from needle.shared.search.queryops import parse_ops

MD_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|<>~])")
MIN_CONTENT_CHARS = 100
MAX_CONTENT_CHARS = 1_000_000


def _result(d: dict[str, Any]) -> SearchResult:
    text = MD_ESCAPE_RE.sub(r"\1", d.get("content") or "").strip()
    title = None
    if text.startswith("# "):
        head, _, text = text.partition("\n")
        title = head[2:].strip() or None
    return SearchResult(
        url=d["url"],
        title=title,
        snippet=text.strip() or None,
        published_date=d.get("published_date") or None,
    )


class SeltzClient(HttpSearchClient):
    engine = "seltz"
    base_url = "https://api.seltz.ai"

    def __init__(self, *, api_key: str, snippet_chars: int = 0, timeout_s: float = 30.0) -> None:
        super().__init__(api_key=api_key, timeout_s=timeout_s)
        self.snippet_chars = snippet_chars

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        max_chars = clamped_chars(self.snippet_chars, MIN_CONTENT_CHARS, MAX_CONTENT_CHARS)
        body: dict[str, Any] = {
            "query": ops.text,
            "max_results": num_results,
            "fields": {"content": {"max_characters_per_result": max_chars} if max_chars else True},
        }
        if ops.sites:
            body["include_domains"] = list(ops.sites)
        if ops.after:
            body["from_date"] = ops.after.isoformat()
        if ops.before:
            body["to_date"] = ops.before.isoformat()
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/v1/search",
            json=body,
            headers={"x-api-key": self.api_key},
        )
        if err is not None:
            return None, err
        raw = payload.get("documents") if isinstance(payload, dict) else None
        results = [
            _result(d)
            for d in (raw if isinstance(raw, list) else [])
            if isinstance(d, dict) and d.get("url")
        ]
        return results[:num_results], None
