import asyncio
from dataclasses import dataclass
from typing import Any

from keenbench.finance.canon import gold_in_text
from keenbench.finance.judge import judge_answer
from keenbench.finance.models import FRESHNESS_LADDER, cues_for
from keenbench.shared.llm import LLMClient
from keenbench.shared.recall import (
    first_rank,
    group_recall,
    recall_summary,
    run_known_item_eval,
    ultimate_per_query,
)
from keenbench.shared.search import (
    DEFAULT_SNIPPET_CHARS,
    SearchClient,
    SearchResult,
    capped_snippet,
    titled_snippet,
)


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


def result_answers(query: GoldQuery, result: SearchResult, *, snippet_chars: int) -> bool:
    text = titled_snippet(result, snippet_chars)
    return gold_in_text(
        query.field_type,
        query.value,
        query.aliases,
        text=text,
        url=result.url,
        cues=cues_for(query.field),
    )


def _scoreable(pq: dict) -> bool:
    return pq["search_error"] is None and not (pq["judge_errors"] and pq["hit_rank"] is None)


def _summary(per_query: list[dict], latency: dict | None) -> dict[str, Any]:
    scored = [pq for pq in per_query if _scoreable(pq)]
    return {
        **recall_summary(per_query, scored, latency),
        "judged_results": sum(pq["judged"] for pq in per_query),
        "judge_errors": sum(pq["judge_errors"] for pq in per_query),
        "judge_upgrades": sum(
            1 for pq in scored if pq["hit_rank"] is not None and pq["hit_rank"] != pq["det_rank"]
        ),
        "by_field": group_recall(scored, lambda pq: pq["field"]),
        "by_bucket": group_recall(scored, lambda pq: pq["bucket"]),
        "by_syntax": group_recall(scored, lambda pq: pq["syntax"]),
        "by_tier": group_recall([pq for pq in scored if pq["tier"]], lambda pq: pq["tier"]),
        "by_freshness": _ladder_order(group_recall(scored, lambda pq: pq["freshness_window"])),
    }


def _ultimate(query_outs: list[list[dict]], *, cap: int) -> list[dict]:
    eligible_outs = [[e for e in entries if _scoreable(e)] for entries in query_outs]
    pooled = [
        eligible or entries for eligible, entries in zip(eligible_outs, query_outs, strict=True)
    ]
    out = ultimate_per_query(pooled, cap=cap)
    for pq, eligible, entries in zip(out, eligible_outs, query_outs, strict=True):
        pq["det_rank"] = pq["hit_rank"]
        pq["judged"] = 0
        pq["judge_errors"] = 0 if eligible else sum(e["judge_errors"] for e in entries)
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
    snippet_chars: int = DEFAULT_SNIPPET_CHARS,
    judge: LLMClient | None = None,
    judge_concurrency: int = 8,
) -> dict[str, Any]:
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
                snippet=capped_snippet(result, snippet_chars),
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
        det_matches = [result_answers(query, r, snippet_chars=snippet_chars) for r in results]
        det_rank = first_rank(det_matches)
        pq["det_rank"] = det_rank
        pq["hit_rank"] = det_rank
        judge_matches: list[bool | None] = [None] * len(results)
        if judge is not None:
            cutoff = det_rank - 1 if det_rank is not None else len(results)
            verdicts = await asyncio.gather(*[judge_result(query, r) for r in results[:cutoff]])
            pq["judged"] = len(verdicts)
            pq["judge_errors"] = sum(1 for _, errored in verdicts if errored)
            judge_matches[: len(verdicts)] = [verdict for verdict, _ in verdicts]
            judge_rank = first_rank(judge_matches)
            if judge_rank is not None:
                pq["hit_rank"] = judge_rank
        pq["results"] = [
            {
                "url": r.url,
                "title": r.title,
                "snippet": capped_snippet(r, snippet_chars),
                "det_match": det,
                "judge_match": jm,
            }
            for r, det, jm in zip(results, det_matches, judge_matches, strict=True)
        ]
        return pq

    return await run_known_item_eval(
        queries,
        engines,
        eval_engine,
        _summary,
        num_results=num_results,
        snippet_chars=snippet_chars,
        ultimate_fn=_ultimate,
        extra={"judged": judge is not None},
    )
