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
    NDCG_K,
    apply_redundancy_penalties,
    dcg_at_k,
    normalize_url,
)
from keenbench.shared.recall import ULTIMATE
from keenbench.shared.search import SearchClient, SearchResult, latency_stats, search_all


@dataclass(frozen=True)
class EvalQuery:
    text: str
    today: str


@dataclass(frozen=True)
class QueryRun:
    searches: list[Any]
    judgements: list[list[Judgement | None]]
    n_judged: int
    profile: dict[str, Any] | None


def _score_query(
    query: EvalQuery,
    results: list[SearchResult] | None,
    search_error: dict[str, str] | None,
    judgements: list[Judgement | None],
    *,
    k: int,
    profile: dict[str, Any] | None,
    idcg: float | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "query": query.text,
        "query_profile": profile,
        "ndcg": None,
        "dcg": None,
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
    ratings = [j.rating if j is not None else None for j in judgements]
    rated = [r for r in ratings if r is not None]
    out["ratings"] = ratings
    out["judge_errors"] = len(ratings) - len(rated)
    if len(rated) == len(ratings):
        penalized = apply_redundancy_penalties(
            [r.url for r in results], rated, query_text=query.text
        )
        out["penalized_ratings"] = penalized
        out["dcg"] = dcg_at_k(penalized, k=k)
        if idcg:
            out["ndcg"] = out["dcg"] / idcg
    out["results"] = [
        {
            "url": r.url,
            "title": r.title,
            "snippet": r.snippet,
            "rating": j.rating if j is not None else None,
            "label": j.label if j is not None else None,
            "reasoning": j.reasoning if j is not None else None,
            "gates": (j.gates or None) if j is not None else None,
            "penalized": out["penalized_ratings"][i] if out["penalized_ratings"] else None,
        }
        for i, (r, j) in enumerate(zip(results, judgements, strict=True))
    ]
    return out


def _ultimate_query(query: EvalQuery, run: QueryRun, *, num_results: int, k: int) -> dict[str, Any]:
    if all(err is not None for _, err in run.searches):
        error = {"error_type": "all_engines_failed", "error_message": "every engine errored"}
        return _score_query(query, None, error, [], k=k, profile=run.profile)
    best: dict[str, tuple[SearchResult, Judgement | None]] = {}
    for (results, err), judgements in zip(run.searches, run.judgements, strict=True):
        if err is not None:
            continue
        for r, j in zip(results or [], judgements, strict=True):
            norm = normalize_url(r.url)
            cur = best.get(norm)
            if cur is None:
                best[norm] = (r, j)
            elif j is not None and (cur[1] is None or j.rating > cur[1].rating):
                best[norm] = (r, j)
    judged = [(r, j) for r, j in best.values() if j is not None]
    if not judged:
        pooled = [r for r, _ in best.values()]
        return _score_query(query, pooled, None, [None] * len(pooled), k=k, profile=run.profile)
    ordered = sorted(judged, key=lambda rj: -rj[1].rating)[:num_results]
    return _score_query(
        query,
        [r for r, _ in ordered],
        None,
        [j for _, j in ordered],
        k=k,
        profile=run.profile,
    )


def _summarize(per_query: list[dict[str, Any]], *, latencies_ms: list[float]) -> dict[str, Any]:
    for pq in per_query:
        pq["score"] = pq["ndcg"]
    scored = [pq["ndcg"] for pq in per_query if pq["ndcg"] is not None]
    return {
        "mean_ndcg": sum(scored) / len(scored) if scored else 0.0,
        "num_scored": len(scored),
        "search_errors": sum(1 for pq in per_query if pq["search_error"] is not None),
        "judge_errors": sum(pq["judge_errors"] for pq in per_query),
        "latency": latency_stats(latencies_ms),
        "per_query": per_query,
    }


async def run_ndcg(
    queries: list[EvalQuery],
    engines: dict[str, SearchClient],
    judge: LLMClient,
    *,
    num_results: int = 5,
    k: int = NDCG_K,
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

    async def judge_query(
        query: EvalQuery, searches: list[Any], profile: QueryProfile | None
    ) -> QueryRun:
        keyed: list[list[tuple]] = []
        unique: dict[tuple, SearchResult] = {}
        for results, err in searches:
            keys = []
            if err is None:
                for r in results or []:
                    key = (normalize_url(r.url), r.title, r.snippet, r.published_date)
                    keys.append(key)
                    unique.setdefault(key, r)
            keyed.append(keys)
        judged = await asyncio.gather(*[judge_pair(query, doc, profile) for doc in unique.values()])
        by_key = dict(zip(unique.keys(), judged, strict=True))
        return QueryRun(
            searches=searches,
            judgements=[[by_key[key] for key in keys] for keys in keyed],
            n_judged=len(unique),
            profile=asdict(profile) if profile is not None else None,
        )

    searches_by_query = await search_all(
        engines, [q.text for q in queries], num_results=num_results
    )

    profiles = await asyncio.gather(*[classify(q) for q in queries])
    query_outs = await asyncio.gather(
        *[
            judge_query(query, searches, profile)
            for query, searches, profile in zip(queries, searches_by_query, profiles, strict=True)
        ]
    )

    ultimate_pqs = [
        _ultimate_query(query, run, num_results=num_results, k=k)
        for query, run in zip(queries, query_outs, strict=True)
    ]
    idcgs = [pq["dcg"] or None for pq in ultimate_pqs]
    for pq, idcg in zip(ultimate_pqs, idcgs, strict=True):
        if idcg:
            pq["ndcg"] = 1.0

    engines_out: dict[str, dict[str, Any]] = {}
    for ni, name in enumerate(names):
        per_query = []
        for query, run, idcg in zip(queries, query_outs, idcgs, strict=True):
            results, err = run.searches[ni]
            per_query.append(
                _score_query(
                    query, results, err, run.judgements[ni], k=k, profile=run.profile, idcg=idcg
                )
            )
        engines_out[name] = _summarize(per_query, latencies_ms=engines[name].latencies_ms)
    if names:
        engines_out[ULTIMATE] = _summarize(ultimate_pqs, latencies_ms=[])

    return {
        "num_queries": len(queries),
        "num_results": num_results,
        "k": k,
        "judged_pairs": sum(run.n_judged for run in query_outs),
        "engines": engines_out,
    }
