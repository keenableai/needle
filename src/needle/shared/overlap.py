from collections.abc import Callable
from typing import Any

from needle.shared.metrics import normalize_url
from needle.shared.recall import ULTIMATE

TS_FMT = "%Y-%m-%dT%H:%MZ"
UNIQUENESS_START = "2026-08-01T00:00Z"


GOOD_LABELS = frozenset({"HM", "FullyM"})


def _engine_sets(
    report: dict[str, Any], of_pq: Callable[[dict[str, Any]], Any]
) -> dict[str, list[Any]]:
    return {
        name: [None if pq["search_error"] is not None else of_pq(pq) for pq in e["per_query"]]
        for name, e in report["engines"].items()
        if name != ULTIMATE
    }


FAMILIES = {
    "keenable-realtime": "keenable",
    "exa-instant": "exa",
    "exa-lite": "exa",
    "parallel-turbo": "parallel",
    "perplexity-fast": "perplexity",
    "brave-llmcontext": "brave",
}


def _all_urls(pq: dict[str, Any]) -> set[str]:
    return {normalize_url(r["url"]) for r in pq["results"]}


def _low_urls(pq: dict[str, Any]) -> set[str]:
    return {
        normalize_url(r["url"])
        for r in pq["results"]
        if r.get("label") and r["label"] not in GOOD_LABELS
    }


def _relevant_urls(pq: dict[str, Any]) -> set[str]:
    return {
        normalize_url(r["url"])
        for rank, r in enumerate(pq["results"], start=1)
        if r.get("label") in GOOD_LABELS or rank == pq.get("hit_rank")
    }


def overlap_rows(report: dict[str, Any], *, ts: str) -> list[dict[str, Any]]:
    url_sets = _engine_sets(report, _all_urls)
    low_sets = _engine_sets(report, _low_urls)
    names = list(url_sets)
    rows = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            suspect = 0
            low_shared_urls = 0
            shared_urls = 0
            union_urls = 0
            n = 0
            for qi, (sa, sb) in enumerate(zip(url_sets[a], url_sets[b], strict=True)):
                if sa is None or sb is None or not (sa or sb):
                    continue
                low = (low_sets[a][qi] or set()) & (low_sets[b][qi] or set())
                low_shared_urls += len(low)
                shared_urls += len(sa & sb)
                union_urls += len(sa | sb)
                suspect += len(low) >= 1 or len(sa & sb) >= 3
                n += 1
            rows.append(
                {
                    "ts": ts,
                    "a": a,
                    "b": b,
                    "num_suspect": suspect,
                    "low_shared_urls": low_shared_urls,
                    "shared_urls": shared_urls,
                    "union_urls": union_urls,
                    "num_queries": n,
                }
            )
    return rows


def uniqueness_rows(report: dict[str, Any], *, ts: str) -> list[dict[str, Any]]:
    url_sets = _engine_sets(report, _all_urls)
    rel_sets = _engine_sets(report, _relevant_urls)
    rows = []
    for name, sets in url_sets.items():
        unique = total = rel_unique = 0
        for i, s in enumerate(sets):
            if s is None:
                continue
            others = [
                p
                for n2, o in url_sets.items()
                if FAMILIES.get(n2, n2) != FAMILIES.get(name, name) and (p := o[i]) is not None
            ]
            if not others:
                continue
            other_urls = set().union(*others)
            total += len(s)
            unique += len(s - other_urls)
            rel_unique += len(rel_sets[name][i] - other_urls)
        rows.append(
            {
                "ts": ts,
                "engine": name,
                "unique_urls": unique,
                "total_urls": total,
                "unique_relevant_urls": rel_unique,
            }
        )
    return rows


def independence_totals(
    overlap: list[dict[str, Any]], uniqueness: list[dict[str, Any]], *, since: str = ""
) -> dict[str, list[dict[str, Any]]]:
    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    for r in overlap:
        if r["ts"] < since:
            continue
        a, b = sorted((r["a"], r["b"]))
        t = pairs.setdefault(
            (a, b),
            {
                "a": a,
                "b": b,
                "num_suspect": 0,
                "low_shared_urls": 0,
                "num_queries": 0,
                "shared_urls": 0,
                "union_urls": 0,
            },
        )
        if r.get("num_suspect") is not None:
            t["num_suspect"] += r["num_suspect"]
            t["low_shared_urls"] += r.get("low_shared_urls") or 0
            t["num_queries"] += r["num_queries"]
        if r.get("union_urls") is not None:
            t["shared_urls"] += r["shared_urls"]
            t["union_urls"] += r["union_urls"]
    engines: dict[str, dict[str, Any]] = {}
    for r in uniqueness:
        if r["ts"] < max(since, UNIQUENESS_START):
            continue
        t = engines.setdefault(
            r["engine"],
            {"engine": r["engine"], "unique_urls": 0, "total_urls": 0, "unique_relevant_urls": 0},
        )
        for k in ("unique_urls", "total_urls", "unique_relevant_urls"):
            t[k] += r[k]
    return {"overlap": list(pairs.values()), "uniqueness": list(engines.values())}
