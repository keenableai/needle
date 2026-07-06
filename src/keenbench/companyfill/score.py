import asyncio
from dataclasses import dataclass
from typing import Any

from keenbench.companyfill.canon import gold_in_text
from keenbench.companyfill.judge import judge_answer
from keenbench.companyfill.models import FRESHNESS_LADDER, cues_for
from keenbench.shared.llm import LLMClient
from keenbench.shared.recall import classify_misses, group_recall
from keenbench.shared.search import SearchClient, SearchResult, latency_stats


@dataclass(frozen=True)
class GoldQuery:
    text: str
    field: str
    field_type: str
    value: Any
    aliases: tuple[str, ...]
    bucket: str
    freshness_window: str
    syntax: str = "plain"
    tier: str = ""


def _capped_snippet(result: SearchResult, snippet_chars: int) -> str:
    snippet = result.snippet or ""
    return snippet[:snippet_chars] if snippet_chars > 0 else snippet


def result_answers(query: GoldQuery, result: SearchResult, *, snippet_chars: int) -> bool:
    text = " ".join(part for part in (result.title, _capped_snippet(result, snippet_chars)) if part)
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
    judge: LLMClient | None = None,
    judge_concurrency: int = 8,
) -> dict[str, Any]:
    engine_names = list(engines)
    judge_sem = asyncio.Semaphore(max(1, judge_concurrency))

    async def judge_result(query: GoldQuery, result: SearchResult) -> tuple[bool | None, bool]:
        assert judge is not None
        async with judge_sem:
            verdict, err = await judge_answer(
                judge,
                query_text=query.text,
                field=query.field,
                value=query.value,
                aliases=query.aliases,
                title=result.title,
                url=result.url,
                snippet=_capped_snippet(result, snippet_chars),
            )
        return verdict, err is not None

    async def eval_engine(query: GoldQuery, results: list[SearchResult] | None, err: Any) -> dict:
        pq = {
            "query": query.text,
            "field": query.field,
            "value": query.value,
            "bucket": query.bucket,
            "syntax": query.syntax,
            "tier": query.tier,
            "freshness_window": query.freshness_window,
            "hit_rank": None,
            "det_rank": None,
            "judged": 0,
            "judge_errors": 0,
            "n_results": 0,
            "results": [],
            "search_error": err,
        }
        if err is not None:
            return pq
        results = results or []
        pq["n_results"] = len(results)
        pq["results"] = [
            {"url": r.url, "title": r.title, "snippet": _capped_snippet(r, snippet_chars)}
            for r in results
        ]
        det_rank = first_hit_rank(query, results, snippet_chars=snippet_chars)
        pq["det_rank"] = det_rank
        pq["hit_rank"] = det_rank
        if judge is not None:
            cutoff = det_rank - 1 if det_rank is not None else len(results)
            candidates = list(enumerate(results[:cutoff], start=1))
            verdicts = await asyncio.gather(*[judge_result(query, r) for _, r in candidates])
            pq["judged"] = len(candidates)
            pq["judge_errors"] = sum(1 for _, errored in verdicts if errored)
            yes_ranks = [rank for (rank, _), (v, _) in zip(candidates, verdicts, strict=True) if v]
            if yes_ranks:
                pq["hit_rank"] = min(yes_ranks)
        return pq

    async def run_query(query: GoldQuery) -> list[dict]:
        searches = await asyncio.gather(
            *[engines[n].search(query.text, num_results=num_results) for n in engine_names]
        )
        return await asyncio.gather(*[eval_engine(query, r, e) for r, e in searches])

    query_outs = await asyncio.gather(*[run_query(q) for q in queries])

    engines_out: dict[str, dict[str, Any]] = {}
    for idx, name in enumerate(engine_names):
        per_query = [entries[idx] for entries in query_outs]
        scored = [
            pq
            for pq in per_query
            if pq["search_error"] is None and not (pq["judge_errors"] and pq["hit_rank"] is None)
        ]
        hits = [pq for pq in scored if pq["hit_rank"] is not None]
        engines_out[name] = {
            "recall_at_k": len(hits) / len(scored) if scored else 0.0,
            "mrr_at_k": (sum(1.0 / pq["hit_rank"] for pq in hits) / len(scored) if scored else 0.0),
            "num_scored": len(scored),
            "search_errors": sum(1 for pq in per_query if pq["search_error"] is not None),
            "judged_results": sum(pq["judged"] for pq in per_query),
            "judge_errors": sum(pq["judge_errors"] for pq in per_query),
            "judge_upgrades": sum(
                1
                for pq in scored
                if pq["hit_rank"] is not None and pq["hit_rank"] != pq["det_rank"]
            ),
            "latency": latency_stats(engines[name].latencies_ms),
            "by_field": group_recall(scored, lambda pq: pq["field"]),
            "by_bucket": group_recall(scored, lambda pq: pq["bucket"]),
            "by_syntax": group_recall(scored, lambda pq: pq["syntax"]),
            "by_tier": group_recall([pq for pq in scored if pq["tier"]], lambda pq: pq["tier"]),
            "by_freshness": _ladder_order(group_recall(scored, lambda pq: pq["freshness_window"])),
            "per_query": per_query,
        }

    classify_misses(query_outs, engine_names, engines_out)

    return {
        "num_queries": len(queries),
        "num_results": num_results,
        "snippet_chars": snippet_chars,
        "judged": judge is not None,
        "engines": engines_out,
    }
