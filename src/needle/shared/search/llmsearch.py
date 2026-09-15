import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from needle.shared.search.base import SearchResult

MAX_OUTPUT_TOKENS = 32000
SYSTEM_PROMPT = (
    "Call the web search tool exactly once, passing the user's message verbatim as the "
    "query: do not rewrite, shorten, or drop any part of it, including operators such as "
    "site: or after:. Then reply with only a JSON array, no prose and no code fence: one "
    "object per search result you received, in the order received, with keys url, title, "
    "snippet. Copy the snippet text verbatim from the search result; do not paraphrase or "
    "summarize."
)
_FENCE = re.compile(r"^```(?:json)?|```$", re.M)


def strip_utm(url: str) -> str:
    parts = urlsplit(url)
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.startswith("utm_")
    ]
    return urlunsplit(parts._replace(query=urlencode(kept)))


def parse_rows(text: str) -> dict[str, dict[str, Any]]:
    cleaned = _FENCE.sub("", text).strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start < 0 or end < start:
        return {}
    try:
        rows = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return {
        strip_utm(r["url"]): r
        for r in rows
        if isinstance(r, dict) and isinstance(r.get("url"), str) and r["url"]
    }


def hits_with_rows(
    hits: list[SearchResult], rows: dict[str, dict[str, Any]], num_results: int
) -> list[SearchResult]:
    out: list[SearchResult] = []
    seen: set[str] = set()
    for hit in hits:
        if hit.url in seen:
            continue
        seen.add(hit.url)
        row = rows.get(hit.url, {})
        title = row.get("title") if isinstance(row.get("title"), str) else None
        snippet = row.get("snippet") if isinstance(row.get("snippet"), str) else None
        out.append(
            SearchResult(
                url=hit.url,
                title=hit.title or title,
                snippet=snippet or None,
                published_date=hit.published_date,
            )
        )
    return out[:num_results]
