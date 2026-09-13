import os
from typing import Any

from needle.shared.search.base import HttpSearchClient, SearchResult
from needle.shared.search.llmsearch import SYSTEM_PROMPT, user_prompt
from needle.shared.search.queryops import parse_ops


class ClaudeSearchClient(HttpSearchClient):
    engine = "claude-search"
    base_url = "https://api.anthropic.com"

    def __init__(self, *, api_key: str, model: str | None = None, timeout_s: float = 120.0) -> None:
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
            "max_tokens": 1024,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_prompt(ops)}],
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
        return _cited_results(blocks if isinstance(blocks, list) else [], num_results)


def _cited_results(
    blocks: list[Any], num_results: int
) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
    page_age: dict[str, str] = {}
    cited: dict[str, dict[str, Any]] = {}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "web_search_tool_result":
            content = block.get("content")
            if isinstance(content, dict):
                return None, {
                    "error_type": "api_error",
                    "error_message": str(content.get("error_code")),
                }
            for r in content if isinstance(content, list) else []:
                if isinstance(r, dict) and r.get("url") and r.get("page_age"):
                    page_age[r["url"]] = r["page_age"]
        elif block.get("type") == "text":
            for c in block.get("citations") or []:
                if not isinstance(c, dict) or not c.get("url"):
                    continue
                entry = cited.setdefault(c["url"], {"title": c.get("title"), "quotes": []})
                if c.get("cited_text"):
                    entry["quotes"].append(c["cited_text"])
    results = [
        SearchResult(
            url=url,
            title=entry["title"],
            snippet=" ".join(entry["quotes"]) or None,
            published_date=page_age.get(url),
        )
        for url, entry in cited.items()
    ]
    return results[:num_results], None
