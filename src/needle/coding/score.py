import re
from dataclasses import dataclass, field
from typing import Any

from needle.coding.sources import page_key
from needle.shared.recall import (
    answered,
    build_match_rows,
    first_rank,
    group_recall,
    recall_summary,
    run_known_item_eval,
)
from needle.shared.search import (
    DEFAULT_SNIPPET_CHARS,
    SearchClient,
    SearchResult,
    capped_snippet,
)

URLISH_RE = re.compile(
    r"(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}/[^\s<>()\"']+",
    re.IGNORECASE,
)


@dataclass
class PageKeys:
    pages: set[str] = field(default_factory=set)

    def as_match_dict(self) -> dict[str, list[str]]:
        return {"page": sorted(self.pages)} if self.pages else {}


def extract_page_keys(result: SearchResult, *, snippet_chars: int) -> PageKeys:
    keys = PageKeys()
    direct = page_key(result.url or "")
    if direct:
        keys.pages.add(direct)
    text = capped_snippet(result, snippet_chars)
    for match in URLISH_RE.finditer(text):
        key = page_key(match.group(0))
        if key:
            keys.pages.add(key)
    return keys


@dataclass(frozen=True)
class GoldCoding:
    text: str
    item_key: str
    bucket: str
    page_key: str
    product: str = ""


def page_match(gold: GoldCoding, found: PageKeys) -> bool:
    return bool(gold.page_key) and gold.page_key in found.pages


def _summary(per_query: list[dict], latency: dict | None) -> dict[str, Any]:
    scored = answered(per_query)
    return {
        **recall_summary(per_query, latency, scored),
        "by_bucket": group_recall(scored, lambda pq: pq["bucket"]),
        "by_product": group_recall(
            [pq for pq in scored if pq.get("product")], lambda pq: pq["product"]
        ),
    }


async def run_coding(
    queries: list[GoldCoding],
    engines: dict[str, SearchClient],
    *,
    num_results: int = 5,
    snippet_chars: int = DEFAULT_SNIPPET_CHARS,
) -> dict[str, Any]:
    async def eval_engine(query: GoldCoding, results: list[SearchResult] | None, err: Any) -> dict:
        pq: dict[str, Any] = {
            "query": query.text,
            "item_key": query.item_key,
            "bucket": query.bucket,
            "product": query.product,
            "hit_rank": None,
            "n_results": 0,
            "results": [],
            "search_error": err,
        }
        if err is not None:
            return pq
        results = results or []
        pq["n_results"] = len(results)
        found = [extract_page_keys(r, snippet_chars=snippet_chars) for r in results]
        matches = [page_match(query, keys) for keys in found]
        pq["results"] = build_match_rows(results, found, matches, snippet_chars=snippet_chars)
        pq["hit_rank"] = first_rank(matches)
        return pq

    return await run_known_item_eval(
        queries,
        engines,
        eval_engine,
        _summary,
        num_results=num_results,
        snippet_chars=snippet_chars,
    )
