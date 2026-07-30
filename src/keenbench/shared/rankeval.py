import asyncio
from dataclasses import asdict, dataclass
from typing import Any

from keenbench.shared.judge import (
    DEFAULT_MAX_CONTENT_CHARS,
    Judgement,
    QueryProfile,
    classify_query,
    judge_one,
)
from keenbench.shared.llm import LLMClient
from keenbench.shared.metrics import (
    RBP_K,
    RBP_P,
    apply_redundancy_penalties,
    normalize_url,
    oracle_order,
    rbp_at_k,
)
from keenbench.shared.recall import ULTIMATE
from keenbench.shared.search import SearchClient, SearchResult, latency_stats


@dataclass(frozen=True)
class EvalQuery:
    text: str
    today: str


@dataclass(frozen=True)
class QueryRun:
    searches: list[Any]
    merged: dict[str, SearchResult]
    judgements_by_url: dict[str, Judgement | None]
    profile: dict[str, Any] | None


def _merge_pair(results: list[SearchResult]) -> SearchResult:
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
    judgements_by_url: dict[str, Judgement | None],
    *,
    k: int,
    profile: dict[str, Any] | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "query": query.text,
        "query_profile": profile,
        "rbp": None,
        "ratings": [],
        "penalized_ratings": [],
        "results": [],
        "n_results": 0,
        "judge_errors": 0,
        "search_error": search_error,
    }
    if search_error is not None:
        return out
    results = results or []
    out["n_results"] = len(results)
    judgements = [judgements_by_url[r.url] for r in results]
    ratings = [j.rating if j is not None else None for j in judgements]
    rated = [r for r in ratings if r is not None]
    out["ratings"] = ratings
    out["judge_errors"] = len(ratings) - len(rated)
    if len(rated) == len(ratings):
        penalized = apply_redundancy_penalties(
            [r.url for r in results], rated, query_text=query.text
        )
        out["penalized_ratings"] = penalized
        out["rbp"] = rbp_at_k(penalized, k=k)
    out["results"] = [
        {
            "url": r.url,
            "title": r.title,
            "snippet": r.snippet,
            "rating": j.rating if j is not None else None,
            "label": j.label if j is not None else None,
            "reasoning": j.reasoning if j is not None else None,
            "penalized": out["penalized_ratings"][i] if out["penalized_ratings"] else None,
        }
        for i, (r, j) in enumerate(zip(results, judgements, strict=True))
    ]
    return out


def _ultimate_query(query: EvalQuery, run: QueryRun, *, num_results: int, k: int) -> dict[str, Any]:
    if all(err is not None for _, err in run.searches):
        error = {"error_type": "all_engines_failed", "error_message": "every engine errored"}
        return _score_query(query, None, error, run.judgements_by_url, k=k, profile=run.profile)
    judged = [
        (url, result, judgement)
        for url, result in run.merged.items()
        if (judgement := run.judgements_by_url[url]) is not None
    ]
    if not judged:
        return _score_query(
            query, list(run.merged.values()), None, run.judgements_by_url, k=k, profile=run.profile
        )
    urls = [url for url, _, _ in judged]
    ratings = [judgement.rating for _, _, judgement in judged]
    order = oracle_order(urls, ratings, query_text=query.text)
    ordered = [judged[i][1] for i in order][:num_results]
    return _score_query(query, ordered, None, run.judgements_by_url, k=k, profile=run.profile)


def _summarize(
    per_query: list[dict[str, Any]], *, k: int, latencies_ms: list[float]
) -> dict[str, Any]:
    scored = [pq["rbp"] for pq in per_query if pq["rbp"] is not None]
    return {
        "mean_rbp": sum(scored) / len(scored) if scored else 0.0,
        "rbp_max": 1.0 - RBP_P**k,
        "num_scored": len(scored),
        "search_errors": sum(1 for pq in per_query if pq["search_error"] is not None),
        "judge_errors": sum(pq["judge_errors"] for pq in per_query),
        "latency": latency_stats(latencies_ms),
        "per_query": per_query,
    }


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
    judge_sem = asyncio.Semaphore(judge_concurrency)

    async def judge_pair(
        query: EvalQuery, doc: SearchResult, profile: QueryProfile | None
    ) -> Judgement | None:
        async with judge_sem:
            judgement, _err = await judge_one(
                judge,
                query.text,
                url=doc.url,
                title=doc.title,
                published=doc.published_date,
                content=doc.snippet,
                today=query.today,
                max_content_chars=max_content_chars,
                profile=profile,
            )
        return judgement

    async def classify(query: EvalQuery) -> QueryProfile | None:
        async with judge_sem:
            profile, _err = await classify_query(judge, query.text, today=query.today)
        return profile

    async def run_query(query: EvalQuery) -> QueryRun:
        searches, profile = await asyncio.gather(
            asyncio.gather(
                *[engines[n].search(query.text, num_results=num_results) for n in names]
            ),
            classify(query),
        )
        pair_docs: dict[str, list[SearchResult]] = {}
        for results, err in searches:
            if err is None:
                for r in results or []:
                    pair_docs.setdefault(normalize_url(r.url), []).append(r)
        merged = {docs[0].url: _merge_pair(docs) for docs in pair_docs.values()}
        judgements = await asyncio.gather(
            *[judge_pair(query, doc, profile) for doc in merged.values()]
        )
        judgements_by_url = {
            r.url: judgement
            for docs, judgement in zip(pair_docs.values(), judgements, strict=True)
            for r in docs
        }
        return QueryRun(
            searches=searches,
            merged=merged,
            judgements_by_url=judgements_by_url,
            profile=asdict(profile) if profile is not None else None,
        )

    query_outs = await asyncio.gather(*[run_query(q) for q in queries])

    engines_out: dict[str, dict[str, Any]] = {}
    for ni, name in enumerate(names):
        per_query = []
        for query, run in zip(queries, query_outs, strict=True):
            results, err = run.searches[ni]
            per_query.append(
                _score_query(query, results, err, run.judgements_by_url, k=k, profile=run.profile)
            )
        engines_out[name] = _summarize(per_query, k=k, latencies_ms=engines[name].latencies_ms)
    if names:
        engines_out[ULTIMATE] = _summarize(
            [
                _ultimate_query(query, run, num_results=num_results, k=k)
                for query, run in zip(queries, query_outs, strict=True)
            ],
            k=k,
            latencies_ms=[],
        )

    return {
        "num_queries": len(queries),
        "num_results": num_results,
        "k": k,
        "judged_pairs": sum(len(run.merged) for run in query_outs),
        "engines": engines_out,
    }
