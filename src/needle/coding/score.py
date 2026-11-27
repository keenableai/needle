from dataclasses import dataclass
from typing import Any

from needle.coding.models import doc_key
from needle.shared.recall import (
    build_match_rows,
    first_rank,
    group_recall,
    recall_summary,
    run_known_item_eval,
    scored_queries,
)
from needle.shared.search import DEFAULT_SNIPPET_CHARS, SearchClient, SearchResult


@dataclass(frozen=True)
class GoldDoc:
    text: str
    doc_key: str
    bucket: str
    syntax: str


@dataclass(frozen=True)
class DocIds:
    key: str | None

    def as_match_dict(self) -> dict[str, list[str]]:
        return {"doc": [self.key]} if self.key else {}


def _summary(per_query: list[dict], latency: dict | None) -> dict[str, Any]:
    scored = scored_queries(per_query)
    return {
        **recall_summary(per_query, latency),
        "by_bucket": group_recall(scored, lambda pq: pq["bucket"]),
        "by_syntax": group_recall(scored, lambda pq: pq["syntax"]),
    }


async def run_coding(
    queries: list[GoldDoc],
    engines: dict[str, SearchClient],
    *,
    num_results: int = 5,
    snippet_chars: int = DEFAULT_SNIPPET_CHARS,
) -> dict[str, Any]:
    async def eval_engine(query: GoldDoc, results: list[SearchResult] | None, err: Any) -> dict:
        pq: dict[str, Any] = {
            "query": query.text,
            "doc_key": query.doc_key,
            "bucket": query.bucket,
            "syntax": query.syntax,
            "hit_rank": None,
            "n_results": 0,
            "results": [],
            "search_error": err,
        }
        if err is not None:
            return pq
        results = results or []
        pq["n_results"] = len(results)
        found = [DocIds(doc_key(r.url or "")) for r in results]
        matches = [f.key == query.doc_key for f in found]
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
        concurrent_search=True,
    )
