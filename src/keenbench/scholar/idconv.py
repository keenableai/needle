from typing import Any

from keenbench.shared.search.base import HttpSearchClient

IDCONV_ENDPOINT = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
BATCH = 100
USER_AGENT = "keenbench/0.1 (contact@keenable.ai)"


class IdConverter(HttpSearchClient):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._cache: dict[str, str | None] = {}

    async def pmc_to_pmid(self, pmcids: list[str]) -> dict[str, str | None]:
        wanted = [p for p in dict.fromkeys(pmcids) if p]
        missing = [p for p in wanted if p not in self._cache]
        for i in range(0, len(missing), BATCH):
            batch = missing[i : i + BATCH]
            keys = [f"PMC{p}" for p in batch]
            payload, err = await self._request_json(
                "GET",
                IDCONV_ENDPOINT,
                params={"ids": ",".join(keys), "format": "json", "tool": "keenbench"},
                headers={"User-Agent": USER_AGENT},
            )
            if err is not None or not isinstance(payload, dict):
                continue
            for rec in payload.get("records", []):
                pmcid = str(rec.get("pmcid") or "")
                if pmcid.upper().startswith("PMC"):
                    bare = pmcid[3:]
                    pmid = rec.get("pmid")
                    self._cache[bare] = str(pmid) if pmid not in (None, "") else None
            for p in batch:
                self._cache.setdefault(p, None)
        return {p: self._cache.get(p) for p in wanted}
