import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from keenbench.companyfill.canon import gold_in_text
from keenbench.companyfill.models import FRESHNESS_LADDER, cues_for
from keenbench.shared.search import SearchClient, SearchResult


@dataclass(frozen=True)
class GoldQuery:
    text: str
    field: str
    field_type: str
    value: Any
    aliases: tuple[str, ...]
    bucket: str
    freshness_window: str


def result_answers(query: GoldQuery, result: SearchResult, *, snippet_chars: int) -> bool:
    snippet = (
        (result.snippet or "")[:snippet_chars] if snippet_chars > 0 else (result.snippet or "")
    )
    text = " ".join(part for part in (result.title, snippet) if part)
    return gold_in_text(
        query.field_type,
        query.value,
        query.aliases,
        text=text,
        url=result.url,
        cues=cues_for(query.field),
    )


def first_hit_rank(
    query: GoldQuery, results: list[SearchResult], *, snippet_chars: int
) -> int | None:
    for rank, result in enumerate(results, start=1):
        if result_answers(query, result, snippet_chars=snippet_chars):
            return rank
    return None


def _group(per_query: list[dict], key: Callable[[dict], str]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict]] = {}
    for pq in per_query:
        if pq["search_error"] is None:
            groups.setdefault(key(pq), []).append(pq)
    out = {}
    for name, pqs in groups.items():
        hits = [pq for pq in pqs if pq["hit_rank"] is not None]
        out[name] = {"n": len(pqs), "recall_at_k": len(hits) / len(pqs)}
    return out


def _ladder_order(groups: dict[str, dict]) -> dict[str, dict]:
    def rank(window: str) -> int:
        return (
            FRESHNESS_LADDER.index(window) if window in FRESHNESS_LADDER else len(FRESHNESS_LADDER)
        )

    return dict(sorted(groups.items(), key=lambda kv: rank(kv[0])))


async def run_answers(
    queries: list[GoldQuery],
    engines: dict[str, SearchClient],
    *,
    num_results: int = 5,
    snippet_chars: int = 500,
) -> dict[str, Any]:
    names = list(engines)

    async def run_query(query: GoldQuery) -> list[Any]:
        return await asyncio.gather(
            *[engines[n].search(query.text, num_results=num_results) for n in names]
        )

    query_outs = await asyncio.gather(*[run_query(q) for q in queries])

    engines_out: dict[str, dict[str, Any]] = {}
    for ni, name in enumerate(names):
        per_query = []
        for query, searches in zip(queries, query_outs, strict=True):
            results, err = searches[ni]
            hit_rank = None
            if err is None:
                hit_rank = first_hit_rank(query, results or [], snippet_chars=snippet_chars)
            per_query.append(
                {
                    "query": query.text,
                    "field": query.field,
                    "bucket": query.bucket,
                    "freshness_window": query.freshness_window,
                    "hit_rank": hit_rank,
                    "n_results": len(results or []) if err is None else 0,
                    "search_error": err,
                }
            )
        scored = [pq for pq in per_query if pq["search_error"] is None]
        hits = [pq for pq in scored if pq["hit_rank"] is not None]
        engines_out[name] = {
            "recall_at_k": len(hits) / len(scored) if scored else 0.0,
            "mrr_at_k": (sum(1.0 / pq["hit_rank"] for pq in hits) / len(scored) if scored else 0.0),
            "num_scored": len(scored),
            "search_errors": len(per_query) - len(scored),
            "by_field": dict(sorted(_group(per_query, lambda pq: pq["field"]).items())),
            "by_bucket": dict(sorted(_group(per_query, lambda pq: pq["bucket"]).items())),
            "by_freshness": _ladder_order(_group(per_query, lambda pq: pq["freshness_window"])),
            "per_query": per_query,
        }

    return {
        "num_queries": len(queries),
        "num_results": num_results,
        "snippet_chars": snippet_chars,
        "engines": engines_out,
    }
