import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from needle.shared.search.base import (
    SearchClient,
    SearchResult,
    capped_snippet,
    latency_stats,
    search_all,
)

ULTIMATE = "ultimate"
ACCOUNT_STATUSES = frozenset({401, 402, 403, 432, 433})
MESSAGE_STATUSES = frozenset({None, 400, 429})
ACCOUNT_MESSAGE = re.compile(
    r"credit[ _]balance|not enough credits|insufficient[ _]credits|usage limit"
    r"|\bquota\b|insufficient_quota|billing|api[ _-]?key",
    re.IGNORECASE,
)
HTTP_STATUS = re.compile(r"(\d{3}):")


def account_side(error: dict[str, str]) -> bool:
    kind, message = error.get("error_type"), error.get("error_message") or ""
    if kind not in ("http_error", "api_error"):
        return False
    status = HTTP_STATUS.match(message) if kind == "http_error" else None
    code = int(status.group(1)) if status else None
    return code in ACCOUNT_STATUSES or (
        code in MESSAGE_STATUSES and ACCOUNT_MESSAGE.search(message) is not None
    )


def counted(pq: dict) -> bool:
    return pq["search_error"] is None or not account_side(pq["search_error"])


def answered(per_query: list[dict]) -> list[dict]:
    return [pq for pq in per_query if counted(pq)]


def error_counts(per_query: list[dict]) -> dict[str, int]:
    errors = [pq["search_error"] for pq in per_query if pq["search_error"] is not None]
    account = sum(1 for e in errors if account_side(e))
    return {
        "search_errors": len(errors),
        "account_errors": account,
        "service_errors": len(errors) - account,
    }


def first_rank(flags: Sequence[object]) -> int | None:
    return next((rank for rank, flag in enumerate(flags, start=1) if flag), None)


def build_match_rows(
    results: list[SearchResult], found: list[Any], matches: list[bool], *, snippet_chars: int
) -> list[dict]:
    return [
        {
            "url": r.url,
            "title": r.title,
            "snippet": capped_snippet(r, snippet_chars),
            "ids": f.as_match_dict(),
            "matched": m,
        }
        for r, f, m in zip(results, found, matches, strict=True)
    ]


def ultimate_per_query(query_outs: list[list[dict]], *, cap: int) -> list[dict]:
    out = []
    for entries in query_outs:
        pq = dict(entries[0], hit_rank=None, n_results=0, results=[])
        scored = [e for e in entries if e["search_error"] is None]
        if scored:
            pq["search_error"] = None
            hit = next(
                (e["results"][e["hit_rank"] - 1] for e in scored if e["hit_rank"] is not None),
                None,
            )
            pooled: dict[str, dict] = {}
            for e in scored:
                for r in e["results"]:
                    pooled.setdefault(r["url"], r)
            rest = [r for url, r in pooled.items() if hit is None or url != hit["url"]]
            pq["results"] = (([hit] if hit else []) + rest)[:cap]
            pq["n_results"] = len(pq["results"])
            pq["hit_rank"] = 1 if hit else None
        else:
            pq["search_error"] = next(
                (e["search_error"] for e in entries if not account_side(e["search_error"])),
                pq["search_error"],
            )
        out.append(pq)
    return out


def recall_summary(
    per_query: list[dict], latency: dict | None, scored: list[dict] | None = None
) -> dict[str, Any]:
    scored = answered(per_query if scored is None else scored)
    for pq in per_query:
        pq["score"] = None
    for pq in scored:
        pq["score"] = 1.0 if pq["hit_rank"] is not None else 0.0
    hits = [pq for pq in scored if pq["hit_rank"] is not None]
    return {
        "recall_at_k": len(hits) / len(scored) if scored else 0.0,
        "mrr_at_k": sum(1.0 / pq["hit_rank"] for pq in hits) / len(scored) if scored else 0.0,
        "num_scored": len(scored),
        **error_counts(per_query),
        "latency": latency,
        "per_query": per_query,
    }


def group_recall(scored: list[dict], key: Callable[[dict], str]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict]] = {}
    for pq in scored:
        groups.setdefault(key(pq), []).append(pq)
    out = {}
    for name, pqs in sorted(groups.items()):
        hits = [pq for pq in pqs if pq["hit_rank"] is not None]
        out[name] = {"n": len(pqs), "recall_at_k": len(hits) / len(pqs)}
    return out


def classify_misses(
    query_outs: list[list[dict]],
    engine_names: list[str],
    engines_out: dict[str, dict[str, Any]],
) -> None:
    any_hit = [any(pq["hit_rank"] is not None for pq in entries) for entries in query_outs]
    for idx, name in enumerate(engine_names):
        system_specific = universal = 0
        for entries, others_found in zip(query_outs, any_hit, strict=True):
            pq = entries[idx]
            if not counted(pq) or pq["hit_rank"] is not None:
                continue
            if others_found:
                system_specific += 1
            else:
                universal += 1
        engines_out[name]["misses_system_specific"] = system_specific
        engines_out[name]["misses_universal"] = universal
    if ULTIMATE in engines_out:
        engines_out[ULTIMATE]["misses_system_specific"] = 0
        engines_out[ULTIMATE]["misses_universal"] = sum(
            1 for pq in engines_out[ULTIMATE]["per_query"] if counted(pq) and pq["hit_rank"] is None
        )


async def run_known_item_eval(
    queries: Sequence[Any],
    engines: dict[str, SearchClient],
    eval_engine: Callable[[Any, list[SearchResult] | None, Any], Awaitable[dict]],
    summary: Callable[[list[dict], dict | None], dict[str, Any]],
    *,
    num_results: int,
    snippet_chars: int,
    ultimate_fn: Callable[..., list[dict]] = ultimate_per_query,
    extra: dict[str, Any] | None = None,
    concurrent_search: bool = False,
) -> dict[str, Any]:
    engine_names = list(engines)
    searches_by_query = await search_all(
        engines,
        [q.text for q in queries],
        num_results=num_results,
        concurrent_search=concurrent_search,
    )
    query_outs = await asyncio.gather(
        *[
            asyncio.gather(*[eval_engine(query, s.results, s.error) for s in searches])
            for query, searches in zip(queries, searches_by_query, strict=True)
        ]
    )
    for entries, searches in zip(query_outs, searches_by_query, strict=True):
        for out, search in zip(entries, searches, strict=True):
            out["queried_at"] = search.queried_at

    engines_out: dict[str, dict[str, Any]] = {}
    for idx, name in enumerate(engine_names):
        per_query = [entries[idx] for entries in query_outs]
        engines_out[name] = summary(per_query, latency_stats(engines[name].latencies_ms))
    if engine_names:
        engines_out[ULTIMATE] = summary(ultimate_fn(query_outs, cap=num_results), None)
        engines_out[ULTIMATE]["mrr_at_k"] = None
        for pq in engines_out[ULTIMATE]["per_query"]:
            pq["queried_at"] = None

    classify_misses(query_outs, engine_names, engines_out)

    return {
        "num_queries": len(queries),
        "num_results": num_results,
        "snippet_chars": snippet_chars,
        **(extra or {}),
        "engines": engines_out,
    }
