from collections.abc import Callable
from typing import Any

ULTIMATE = "ultimate"


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
        out.append(pq)
    return out


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
            if pq["search_error"] is not None or pq["hit_rank"] is not None:
                continue
            if others_found:
                system_specific += 1
            else:
                universal += 1
        engines_out[name]["misses_system_specific"] = system_specific
        engines_out[name]["misses_universal"] = universal
