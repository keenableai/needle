import asyncio
from typing import Any

from keenbench.shared.judge import DEFAULT_MAX_CONTENT_CHARS, judge_one
from keenbench.shared.llm import LLMClient
from keenbench.shared.metrics import RBP_K, RBP_MAX, rbp_at_k
from keenbench.shared.search import SearchClient, SearchResult


async def _score_query(
    judge: LLMClient,
    query: str,
    results: list[SearchResult] | None,
    *,
    search_error: dict[str, str] | None,
    today: str,
    k: int,
    sem: asyncio.Semaphore,
    max_content_chars: int,
) -> dict[str, Any]:
    # rbp stays None (excluded from the mean) when the search failed or any
    # judgement is missing — a defaulted rating of 0 would bias the comparison.
    out: dict[str, Any] = {
        "query": query,
        "rbp": None,
        "ratings": [],
        "n_results": 0,
        "judge_errors": 0,
        "search_error": search_error,
    }
    if search_error is not None:
        return out
    if not results:
        out["rbp"] = 0.0
        return out
    out["n_results"] = len(results)

    async def judge_result(r: SearchResult) -> int | None:
        async with sem:
            judgement, _err = await judge_one(
                judge,
                query,
                url=r.url,
                title=r.title,
                published=r.published_date,
                content=r.snippet,
                today=today,
                max_content_chars=max_content_chars,
            )
        return judgement.rating if judgement is not None else None

    ratings = list(await asyncio.gather(*[judge_result(r) for r in results]))
    out["ratings"] = ratings
    out["judge_errors"] = sum(1 for r in ratings if r is None)
    if out["judge_errors"] == 0:
        out["rbp"] = rbp_at_k([r for r in ratings if r is not None], k=k)
    return out


async def run_rbp(
    query_texts: list[str],
    engines: dict[str, SearchClient],
    judge: LLMClient,
    *,
    num_results: int = 5,
    k: int = RBP_K,
    today: str,
    judge_concurrency: int = 8,
    max_content_chars: int = DEFAULT_MAX_CONTENT_CHARS,
) -> dict[str, Any]:
    sem = asyncio.Semaphore(judge_concurrency)

    async def run_engine(name: str, client: SearchClient) -> tuple[str, dict[str, Any]]:
        searches = await asyncio.gather(
            *[client.search(q, num_results=num_results) for q in query_texts]
        )
        per_query = await asyncio.gather(
            *[
                _score_query(
                    judge,
                    q,
                    results,
                    search_error=err,
                    today=today,
                    k=k,
                    sem=sem,
                    max_content_chars=max_content_chars,
                )
                for q, (results, err) in zip(query_texts, searches, strict=True)
            ]
        )
        scored = [pq["rbp"] for pq in per_query if pq["rbp"] is not None]
        return name, {
            "mean_rbp_at_5": sum(scored) / len(scored) if scored else 0.0,
            "rbp_max": RBP_MAX,
            "num_scored": len(scored),
            "search_errors": sum(1 for pq in per_query if pq["search_error"] is not None),
            "judge_errors": sum(pq["judge_errors"] for pq in per_query),
            "per_query": per_query,
        }

    engines_out = await asyncio.gather(*[run_engine(n, c) for n, c in engines.items()])
    return {
        "num_queries": len(query_texts),
        "num_results": num_results,
        "engines": dict(engines_out),
    }
