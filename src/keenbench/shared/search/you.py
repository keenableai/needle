from typing import Any

from keenbench.shared.search.base import HttpSearchClient, SearchResult
from keenbench.shared.search.queryops import parse_ops

MAX_COUNT = 100


class YouClient(HttpSearchClient):
    engine = "you"
    base_url = "https://ydc-index.io"

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        body: dict[str, Any] = {"query": ops.text, "count": min(num_results, MAX_COUNT)}
        if ops.sites:
            body["include_domains"] = list(ops.sites)
        if (fresh := ops.freshness_window()) is not None:
            body["freshness"] = fresh
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/v1/search",
            json=body,
            headers={"X-API-Key": self.api_key},
        )
        if err is not None:
            return None, err
        sections = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(sections, dict):
            sections = {}
        results: list[SearchResult] = []
        seen: set[str] = set()
        for section in ("web", "news"):
            raw = sections.get(section)
            for r in raw if isinstance(raw, list) else []:
                if not isinstance(r, dict) or not r.get("url") or r["url"] in seen:
                    continue
                seen.add(r["url"])
                results.append(
                    SearchResult(
                        url=r["url"],
                        title=r.get("title") or None,
                        snippet="\n".join(r.get("snippets") or []) or r.get("description") or None,
                        published_date=r.get("page_age") or None,
                    )
                )
        return results[:num_results], None
