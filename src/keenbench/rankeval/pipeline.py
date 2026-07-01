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
    today: str,
    k: int,
    sem: asyncio.Semaphore,
    max_content_chars: int,
) -> dict[str, Any]:
    if not results:
        return {"query": query, "rbp": 0.0, "ratings": [], "n_results": 0, "judge_errors": 0}

    async def judge_result(r: SearchResult) -> tuple[int, bool]:
        async with sem:
            judgement, err = await judge_one(
                judge,
                query,
                url=r.url,
                title=r.title,
                published=r.published_date,
                content=r.snippet,
                today=today,
                max_content_chars=max_content_chars,
            )
        return (judgement.rating if judgement is not None else 0), (err is not None)

    judged = await asyncio.gather(*[judge_result(r) for r in results])
    ratings = [rating for rating, _ in judged]
    return {
        "query": query,
        "rbp": rbp_at_k(ratings, k=k),
        "ratings": ratings,
        "n_results": len(results),
        "judge_errors": sum(1 for _, e in judged if e),
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
    no-descriptor Needs-Met judge, and return per-engine mean RBP@k. Engines run
    concurrently; the shared judge semaphore caps total in-flight judge calls."""
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
                    results if err is None else None,
                    today=today,
                    k=k,
                    sem=sem,
                    max_content_chars=max_content_chars,
                )
                for q, (results, err) in zip(query_texts, searches, strict=True)
            ]
        )
        mean_rbp = sum(pq["rbp"] for pq in per_query) / len(per_query) if per_query else 0.0
        return name, {
            "mean_rbp_at_5": mean_rbp,
            "rbp_max": RBP_MAX,
            "search_errors": sum(1 for pq in per_query if pq["n_results"] == 0),
            "judge_errors": sum(pq["judge_errors"] for pq in per_query),
            "per_query": per_query,
        }

    engines_out = await asyncio.gather(*[run_engine(n, c) for n, c in engines.items()])
    return {
        "num_queries": len(query_texts),
        "num_results": num_results,
        "engines": dict(engines_out),
    }
