import os
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from needle.shared.search.base import HttpSearchClient, SearchResult
from needle.shared.search.llmsearch import SYSTEM_PROMPT, user_prompt
from needle.shared.search.queryops import parse_ops


class ChatGptSearchClient(HttpSearchClient):
    engine = "chatgpt-search"
    base_url = "https://api.openai.com"

    def __init__(self, *, api_key: str, model: str | None = None, timeout_s: float = 120.0) -> None:
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
            "instructions": SYSTEM_PROMPT,
            "input": user_prompt(ops),
            "tools": [tool],
            "tool_choice": {"type": "web_search"},
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
        return _cited_results(output if isinstance(output, list) else [])[:num_results], None


def _cited_results(output: list[Any]) -> list[SearchResult]:
    seen: dict[str, SearchResult] = {}
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if not isinstance(part, dict) or part.get("type") != "output_text":
                continue
            text = part.get("text") or ""
            citations = [
                a
                for a in part.get("annotations") or []
                if isinstance(a, dict) and a.get("type") == "url_citation" and a.get("url")
            ]
            citations.sort(key=lambda a: a.get("start_index") or 0)
            prev_end = 0
            for a in citations:
                end = a.get("end_index") or prev_end
                snippet = text[prev_end:end].strip()
                prev_end = max(prev_end, end)
                url = _strip_utm(a["url"])
                if url not in seen:
                    seen[url] = SearchResult(
                        url=url, title=a.get("title"), snippet=snippet.replace("**", "") or None
                    )
    return list(seen.values())


def _strip_utm(url: str) -> str:
    parts = urlsplit(url)
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.startswith("utm_")
    ]
    return urlunsplit(parts._replace(query=urlencode(kept)))
