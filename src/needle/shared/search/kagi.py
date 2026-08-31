import html
import re
from typing import Any

from needle.shared.search.base import HttpSearchClient, SearchResult
from needle.shared.search.queryops import parse_ops

MAX_LIMIT = 1024
TAG_RE = re.compile(r"<[^>]+>")


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return html.unescape(TAG_RE.sub("", value)) or None


class KagiClient(HttpSearchClient):
    engine = "kagi"
    base_url = "https://kagi.com/api/v1"

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        body: dict[str, Any] = {"query": ops.text, "limit": min(num_results, MAX_LIMIT)}
        if ops.sites:
            body["lens"] = {"sites_included": list(ops.sites)}
        filters: dict[str, str] = {}
        if ops.after:
            filters["after"] = ops.after.isoformat()
        if ops.before:
            filters["before"] = ops.before.isoformat()
        if filters:
            body["filters"] = filters
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/search",
            json=body,
            headers={"Authorization": f"Bot {self.api_key}"},
        )
        if err is not None:
            return None, err
        sections = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(sections, dict):
            sections = {}
        results: list[SearchResult] = []
        seen: set[str] = set()
        for section in ("search", "news"):
            raw = sections.get(section)
            for r in raw if isinstance(raw, list) else []:
                if not isinstance(r, dict) or not r.get("url") or r["url"] in seen:
                    continue
                seen.add(r["url"])
                results.append(
                    SearchResult(
                        url=r["url"],
                        title=_clean(r.get("title")),
                        snippet=_clean(r.get("snippet")),
                        published_date=r.get("time") or None,
                    )
                )
        return results[:num_results], None
