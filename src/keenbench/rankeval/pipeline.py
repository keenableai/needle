import asyncio
from typing import Any

from keenbench.shared.judge import DEFAULT_MAX_CONTENT_CHARS, judge_one
from keenbench.shared.llm import LLMClient
from keenbench.shared.metrics import RBP_K, RBP_MAX, rbp_at_k
from keenbench.shared.search import SearchClient, SearchResult


async def _judge_result(
    judge: LLMClient,
    query: str,
    result: SearchResult,
    *,
    today: str,
    sem: asyncio.Semaphore,
    max_content_chars: int,
) -> tuple[int, bool]:
    async with sem:
        judgement, err = await judge_one(
            judge,
            query,
            url=result.url,
            title=result.title,
            published=result.published_date,
            content=result.snippet,
            today=today,
            max_content_chars=max_content_chars,
        )
    return (judgement.rating if judgement is not None else 0), (err is not None)


async def _score_query(
    judge: LLMClient,
    query: str,
    results: list[SearchResult] | None,
    search_error: dict[str, str] | None,
    *,
    today: str,
    k: int,
    sem: asyncio.Semaphore,
    max_content_chars: int,
) -> dict[str, Any]:
    if search_error is not None or not results:
        return {"query": query, "rbp": 0.0, "ratings": [], "n_results": 0, "search_error": True}
    judged = await asyncio.gather(
        *[
            _judge_result(
                judge, query, r, today=today, sem=sem, max_content_chars=max_content_chars
            )
            for r in results
        ]
    )
    ratings = [rating for rating, _ in judged]
    return {
        "query": query,
        "rbp": rbp_at_k(ratings, k=k),
        "ratings": ratings,
        "n_results": len(results),
        "judge_errors": sum(1 for _, e in judged if e),
        "search_error": False,
    }


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
    """Search each query on each engine, judge the top ``num_results`` with the
    no-descriptor Needs-Met judge, and return per-engine mean RBP@k."""
    sem = asyncio.Semaphore(judge_concurrency)
    engines_out: dict[str, Any] = {}
    for name, client in engines.items():
        searches = await asyncio.gather(
            *[client.search(q, num_results=num_results) for q in query_texts]
        )
        per_query = await asyncio.gather(
            *[
                _score_query(
                    judge,
                    q,
                    results,
                    err,
                    today=today,
                    k=k,
                    sem=sem,
                    max_content_chars=max_content_chars,
                )
                for q, (results, err) in zip(query_texts, searches, strict=True)
            ]
        )
        mean_rbp = sum(pq["rbp"] for pq in per_query) / len(per_query) if per_query else 0.0
        engines_out[name] = {
            "mean_rbp_at_5": mean_rbp,
            "rbp_max": RBP_MAX,
            "search_errors": sum(1 for pq in per_query if pq["search_error"]),
            "judge_errors": sum(pq.get("judge_errors", 0) for pq in per_query),
            "per_query": per_query,
        }
    return {"num_queries": len(query_texts), "num_results": num_results, "engines": engines_out}
