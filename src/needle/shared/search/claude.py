import os
from typing import Any

from needle.shared.search.base import HttpSearchClient, SearchResult
from needle.shared.search.llmsearch import (
    MAX_OUTPUT_TOKENS,
    SYSTEM_PROMPT,
    hits_with_rows,
    parse_rows,
)
from needle.shared.search.queryops import parse_ops


class ClaudeSearchClient(HttpSearchClient):
    engine = "claude-search"
    base_url = "https://api.anthropic.com"

    def __init__(self, *, api_key: str, model: str | None = None, timeout_s: float = 180.0) -> None:
        super().__init__(api_key=api_key, timeout_s=timeout_s)
        self.model = model or os.environ.get("NEEDLE_CLAUDE_SEARCH_MODEL", "claude-sonnet-5")

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        tool: dict[str, Any] = {"type": "web_search_20250305", "name": "web_search", "max_uses": 1}
        if ops.sites:
            tool["allowed_domains"] = list(ops.sites)
        body = {
            "model": self.model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": query}],
            "tools": [tool],
        }
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/v1/messages",
            json=body,
            headers={"x-api-key": self.api_key or "", "anthropic-version": "2023-06-01"},
        )
        if err is not None:
            return None, err
        blocks = payload.get("content") if isinstance(payload, dict) else None
        return _results(blocks if isinstance(blocks, list) else [], num_results)


def _results(
    blocks: list[Any], num_results: int
) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
    hits: list[SearchResult] = []
    text: list[str] = []
    searched = False
    tool_error: str | None = None
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "web_search_tool_result":
            content = block.get("content")
            if isinstance(content, dict):
                tool_error = str(content.get("error_code"))
                continue
            searched = True
            for r in content if isinstance(content, list) else []:
                if isinstance(r, dict) and r.get("url"):
                    hits.append(
                        SearchResult(
                            url=r["url"], title=r.get("title"), published_date=r.get("page_age")
                        )
                    )
        elif block.get("type") == "text":
            text.append(block.get("text") or "")
    if tool_error and not searched:
        return None, {"error_type": "api_error", "error_message": tool_error}
    return hits_with_rows(hits, parse_rows("".join(text)), num_results), None
