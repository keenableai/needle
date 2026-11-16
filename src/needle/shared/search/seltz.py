import re
from typing import Any

from needle.shared.search.base import HttpSearchClient, SearchResult
from needle.shared.search.queryops import parse_ops

MD_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|<>~])")


def _title_and_body(content: str) -> tuple[str | None, str]:
    text = MD_ESCAPE_RE.sub(r"\1", content).strip()
    if text.startswith("# "):
        head, _, body = text.partition("\n")
        return head[2:].strip() or None, body.strip()
    return None, text


class SeltzClient(HttpSearchClient):
    engine = "seltz"
    base_url = "https://api.seltz.ai"

    def __init__(self, *, api_key: str, snippet_chars: int = 0, timeout_s: float = 30.0) -> None:
        super().__init__(api_key=api_key, timeout_s=timeout_s)
        self.snippet_chars = snippet_chars

    def _result(self, d: dict[str, Any]) -> SearchResult:
        title, body = _title_and_body(d.get("content") or "")
        return SearchResult(
            url=d["url"],
            title=title,
            snippet=body or None,
            published_date=d.get("published_date") or None,
        )

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        content: dict[str, Any] | bool = (
            {"max_characters_per_result": self.snippet_chars} if self.snippet_chars > 0 else True
        )
        body: dict[str, Any] = {
            "query": ops.text,
            "max_results": num_results,
            "fields": {"content": content},
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
            self._result(d)
            for d in (raw if isinstance(raw, list) else [])
            if isinstance(d, dict) and d.get("url")
        ]
        return results[:num_results], None
