from typing import Any

from needle.finance.score import GoldQuery, answer_summary, run_answers
from needle.haystack.judge import judge_answer
from needle.shared.llm import LLMClient
from needle.shared.search import DEFAULT_SNIPPET_CHARS, SearchClient

DEPTH_BUCKETS = ((70, "55-70"), (85, "70-85"))


def depth_bucket(pct: int) -> str:
    for hi, name in DEPTH_BUCKETS:
        if pct < hi:
            return name
    return "85-100"


def _summary(per_query: list[dict], latency: dict | None) -> dict[str, Any]:
    return answer_summary(
        per_query,
        latency,
        {
            "by_bucket": lambda pq: pq["bucket"],
            "by_syntax": lambda pq: pq["syntax"],
            "by_field_type": lambda pq: pq["field"],
            "by_depth": lambda pq: depth_bucket(pq["depth_pct"]),
        },
    )


async def run_haystack(
    queries: list[GoldQuery],
    engines: dict[str, SearchClient],
    *,
    num_results: int = 5,
    snippet_chars: int = DEFAULT_SNIPPET_CHARS,
    judge: LLMClient | None = None,
    judge_concurrency: int = 8,
) -> dict[str, Any]:
    return await run_answers(
        queries,
        engines,
        num_results=num_results,
        snippet_chars=snippet_chars,
        judge=judge,
        judge_concurrency=judge_concurrency,
        summary_fn=_summary,
        judge_fn=judge_answer,
    )
