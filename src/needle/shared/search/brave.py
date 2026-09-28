from datetime import datetime
from typing import Any

from needle.shared.search.base import HttpSearchClient, SearchResult
from needle.shared.search.queryops import freshness_window, parse_ops

BASE_URL = "https://api.search.brave.com/res/v1"
MAX_QUERY_WORDS = 75
MAX_QUERY_CHARS = 600


def _clip_query(text: str, sites: tuple[str, ...] = ()) -> str:
    site_terms = [f"site:{s}" for s in sites]
    words = text.split()[: max(MAX_QUERY_WORDS - len(site_terms), 0)]
    q = " ".join(words + site_terms)
    while words and len(q) > MAX_QUERY_CHARS:
        words.pop()
        q = " ".join(words + site_terms)
    return q


class BraveClient(HttpSearchClient):
    engine = "brave"
    base_url = BASE_URL

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        params: dict[str, Any] = {
            "q": _clip_query(ops.text, ops.sites),
            "count": min(num_results, 20),
            "country": "us",
            "search_lang": "en",
            "result_filter": "web",
            "text_decorations": "false",
        }
        if fresh := freshness_window(ops):
            params["freshness"] = fresh
        payload, err = await self._request_json(
            "GET",
            f"{self.base_url}/web/search",
            params=params,
            headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
        )
        if err is not None:
            return None, err
        raw_results = payload.get("web", {}).get("results", []) if isinstance(payload, dict) else []
        results = [
            SearchResult(
                url=r["url"],
                title=r.get("title"),
                snippet="\n".join(filter(None, r.get("extra_snippets") or []))
                or r.get("description"),
                published_date=r.get("page_age"),
            )
            for r in raw_results[:num_results]
            if r.get("url")
        ]
        return results, None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _is_iso(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _published(source: Any) -> str | None:
    age = _dict(source).get("age")
    stamps = [a for a in age if _is_iso(a)] if isinstance(age, list) else []
    return max(stamps, key=len) if stamps else None


class BraveLlmContextClient(HttpSearchClient):
    engine = "brave-llmcontext"
    base_url = BASE_URL

    def __init__(self, *, api_key: str, snippet_chars: int = 0, timeout_s: float = 30.0) -> None:
        super().__init__(api_key=api_key, timeout_s=timeout_s)
        self.snippet_chars = snippet_chars

    def _snippet(self, e: dict[str, Any]) -> str | None:
        text = "\n".join(filter(None, e.get("snippets") or []))
        if self.snippet_chars > 0:
            text = text[: self.snippet_chars]
        return text or None

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        body: dict[str, Any] = {
            "q": _clip_query(ops.text, ops.sites),
            "country": "us",
            "search_lang": "en",
        }
        if fresh := freshness_window(ops):
            body["freshness"] = fresh
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/llm/context",
            json=body,
            headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
        )
        if err is not None:
            return None, err
        received = _dict(payload)
        grounding = _dict(received.get("grounding"))
        sources = _dict(received.get("sources"))
        results = [
            SearchResult(
                url=e["url"],
                title=e.get("title") or None,
                snippet=self._snippet(e),
                published_date=_published(sources.get(e["url"])),
            )
            for e in grounding.get("generic") or []
            if isinstance(e, dict) and e.get("url")
        ]
        return results[:num_results], None
