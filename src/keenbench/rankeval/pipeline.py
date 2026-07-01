import asyncio
from dataclasses import dataclass
from typing import Any

from keenbench.shared.judge import DEFAULT_MAX_CONTENT_CHARS, judge_one
from keenbench.shared.llm import LLMClient
from keenbench.shared.metrics import RBP_K, RBP_MAX, apply_redundancy_penalties, rbp_at_k
from keenbench.shared.search import SearchClient, SearchResult


@dataclass(frozen=True)
class EvalQuery:
    text: str
    # Judge "Today's date" anchor; per-query (e.g. from the row's hour_ts) so
    # re-judging an old query set is deterministic instead of drifting with
    # wall clock.
    today: str
    topical_domain: str = "other"


def _merge_pair(results: list[SearchResult]) -> SearchResult:
    """Collapse one (query, url) pair's per-engine results into one judge doc.

    Longest snippet wins (most content for the judge); title/published fall
    back across engines in encounter order.
    """
    snippet = max(results, key=lambda r: len(r.snippet or "")).snippet
    return SearchResult(
        url=results[0].url,
        title=next((r.title for r in results if r.title), None),
        snippet=snippet,
        published_date=next((r.published_date for r in results if r.published_date), None),
    )


def _score_query(
    query: EvalQuery,
    results: list[SearchResult] | None,
    search_error: dict[str, str] | None,
    ratings_by_url: dict[str, int | None],
    *,
    k: int,
) -> dict[str, Any]:
    # rbp stays None (excluded from the mean) when the search failed or any
    # judgement is missing — a defaulted rating of 0 would bias the comparison.
    out: dict[str, Any] = {
        "query": query.text,
        "rbp": None,
        "ratings": [],
        "penalized_ratings": [],
        "n_results": 0,
        "judge_errors": 0,
        "search_error": search_error,
    }
    if search_error is not None:
        return out
    results = results or []
    out["n_results"] = len(results)
    ratings = [ratings_by_url[r.url] for r in results]
    rated = [r for r in ratings if r is not None]
    out["ratings"] = ratings
    out["judge_errors"] = len(ratings) - len(rated)
    if len(rated) == len(ratings):
        penalized = apply_redundancy_penalties(
            [r.url for r in results], rated, query_text=query.text
        )
        out["penalized_ratings"] = penalized
        out["rbp"] = rbp_at_k(penalized, k=k)
    return out


async def run_rbp(
    queries: list[EvalQuery],
    engines: dict[str, SearchClient],
    judge: LLMClient,
    *,
    num_results: int = 5,
    k: int = RBP_K,
    judge_concurrency: int = 8,
    max_content_chars: int = DEFAULT_MAX_CONTENT_CHARS,
) -> dict[str, Any]:
    names = list(engines)
    search_lists = await asyncio.gather(
        *[
            asyncio.gather(*[engines[n].search(q.text, num_results=num_results) for q in queries])
            for n in names
        ]
    )
    searches = dict(zip(names, search_lists, strict=True))

    # One judgement per unique (query, url) pair across all engines — the same
    # document gets one rating everywhere, and overlapping engines don't pay
    # for duplicate LLM calls.
    pairs: dict[tuple[int, str], list[SearchResult]] = {}
    for name in names:
        for qi, (results, err) in enumerate(searches[name]):
            if err is None:
                for r in results or []:
                    pairs.setdefault((qi, r.url), []).append(r)

    sem = asyncio.Semaphore(judge_concurrency)

    async def judge_pair(qi: int, doc: SearchResult) -> int | None:
        async with sem:
            judgement, _err = await judge_one(
                judge,
                queries[qi].text,
                url=doc.url,
                title=doc.title,
                published=doc.published_date,
                content=doc.snippet,
                today=queries[qi].today,
                max_content_chars=max_content_chars,
            )
        return judgement.rating if judgement is not None else None

    pair_keys = list(pairs)
    pair_ratings = await asyncio.gather(
        *[judge_pair(qi, _merge_pair(pairs[(qi, url)])) for qi, url in pair_keys]
    )
    ratings_by_query: dict[int, dict[str, int | None]] = {qi: {} for qi in range(len(queries))}
    for (qi, url), rating in zip(pair_keys, pair_ratings, strict=True):
        ratings_by_query[qi][url] = rating

    engines_out: dict[str, dict[str, Any]] = {}
    for name in names:
        per_query = [
            _score_query(queries[qi], results, err, ratings_by_query[qi], k=k)
            for qi, (results, err) in enumerate(searches[name])
        ]
        scored = [pq["rbp"] for pq in per_query if pq["rbp"] is not None]
        engines_out[name] = {
            "mean_rbp_at_5": sum(scored) / len(scored) if scored else 0.0,
            "rbp_max": RBP_MAX,
            "num_scored": len(scored),
            "search_errors": sum(1 for pq in per_query if pq["search_error"] is not None),
            "judge_errors": sum(pq["judge_errors"] for pq in per_query),
            "per_query": per_query,
        }

    return {
        "num_queries": len(queries),
        "num_results": num_results,
        "judged_pairs": len(pairs),
        "engines": engines_out,
    }
