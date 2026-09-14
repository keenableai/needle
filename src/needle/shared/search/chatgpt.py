import os
from typing import Any

from needle.shared.search.base import HttpSearchClient, SearchResult
from needle.shared.search.llmsearch import (
    MAX_OUTPUT_TOKENS,
    SYSTEM_PROMPT,
    hits_with_rows,
    parse_rows,
    strip_utm,
)
from needle.shared.search.queryops import parse_ops


class ChatGptSearchClient(HttpSearchClient):
    engine = "chatgpt-search"
    base_url = "https://api.openai.com"

    def __init__(self, *, api_key: str, model: str | None = None, timeout_s: float = 180.0) -> None:
        super().__init__(api_key=api_key, timeout_s=timeout_s)
        self.model = model or os.environ.get("NEEDLE_CHATGPT_SEARCH_MODEL", "gpt-5.5")

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        tool: dict[str, Any] = {"type": "web_search", "search_context_size": "low"}
        if ops.sites:
            tool["filters"] = {"allowed_domains": list(ops.sites)}
        body = {
            "model": self.model,
            "reasoning": {"effort": "low"},
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "instructions": SYSTEM_PROMPT,
            "input": query,
            "tools": [tool],
            "tool_choice": {"type": "web_search"},
            "include": ["web_search_call.action.sources"],
        }
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/v1/responses",
            json=body,
            error_field="error",
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        if err is not None:
            return None, err
        output = payload.get("output") if isinstance(payload, dict) else None
        output = output if isinstance(output, list) else []
        return hits_with_rows(_hits(output), parse_rows(_text(output)), num_results), None


def _hits(output: list[Any]) -> list[SearchResult]:
    hits: list[SearchResult] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "web_search_call":
            continue
        action = item.get("action")
        sources = action.get("sources") if isinstance(action, dict) else None
        for src in sources or []:
            if isinstance(src, dict) and src.get("url"):
                hits.append(SearchResult(url=strip_utm(src["url"])))
    return hits


def _text(output: list[Any]) -> str:
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("type") == "output_text":
                parts.append(part.get("text") or "")
    return "".join(parts)
