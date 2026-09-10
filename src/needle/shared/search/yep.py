from typing import Any

import tldextract

from needle.shared.search.base import HttpSearchClient, SearchResult
from needle.shared.search.queryops import parse_ops

MAX_LIMIT = 100
TLD_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    return []


def _first_text(result: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        values = _strings(result.get(key))
        if values:
            return "\n".join(values)
    return None


def _root_domains(sites: tuple[str, ...]) -> tuple[str, ...]:
    roots: list[str] = []
    for site in sites:
        root = TLD_EXTRACT(site).top_domain_under_public_suffix or site
        if root not in roots:
            roots.append(root)
    return tuple(roots)


class YepClient(HttpSearchClient):
    engine = "yep"
    base_url = "https://platform.yep.com"

    def __init__(
        self,
        *,
        api_key: str,
        search_type: str = "highlights",
        language: tuple[str, ...] = ("en",),
        location: str = "",
        timeout_s: float = 30.0,
    ) -> None:
        super().__init__(api_key=api_key, timeout_s=timeout_s)
        self.search_type = search_type
        self.language = language
        self.location = location

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        body: dict[str, Any] = {
            "query": ops.text,
            "type": self.search_type,
            "limit": min(num_results, MAX_LIMIT),
        }
        if self.language:
            body["language"] = list(self.language)
        if self.location:
            body["location"] = self.location
        if domains := _root_domains(ops.sites):
            body["include_domains"] = ",".join(domains)
        if ops.after:
            body["start_published_date"] = ops.after.isoformat()
        if ops.before:
            body["end_published_date"] = ops.before.isoformat()
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/api/search",
            error_field="error",
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        if err is not None:
            return None, err
        raw_results = payload.get("results", []) if isinstance(payload, dict) else []
        results = [
            SearchResult(
                url=r["url"],
                title=_first_text(r, ("title", "name")),
                snippet=_first_text(
                    r,
                    (
                        "highlights",
                        "highlight",
                        "snippets",
                        "snippet",
                        "description",
                        "summary",
                        "text",
                    ),
                ),
                published_date=_first_text(
                    r,
                    ("published_date", "publishedDate", "published_at", "datePublished", "date"),
                ),
            )
            for r in raw_results[:num_results]
            if isinstance(r, dict) and r.get("url")
        ]
        return results, None
