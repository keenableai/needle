from datetime import UTC, date, datetime
from typing import Any

from keenbench.shared.search.base import HttpSearchClient, SearchResult
from keenbench.shared.search.queryops import parse_ops

EPOCH = date(1970, 1, 1)
MAX_COUNT = 100


class YouClient(HttpSearchClient):
    engine = "you"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://ydc-index.io",
        timeout_s: float = 30.0,
    ) -> None:
        super().__init__(timeout_s=timeout_s)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        ops = parse_ops(query)
        body: dict[str, Any] = {"query": ops.text, "count": min(num_results, MAX_COUNT)}
        if ops.sites:
            body["include_domains"] = list(ops.sites)
        if ops.after or ops.before:
            lo = ops.after or EPOCH
            hi = ops.before or datetime.now(UTC).date()
            body["freshness"] = f"{lo.isoformat()}to{hi.isoformat()}"
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
                        raw=r,
                    )
                )
        return results[:num_results], None
