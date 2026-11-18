from collections.abc import Callable, Iterable
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
    "parallel-fast": "parallel",
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


Key = Callable[[dict[str, Any]], dict[str, Any]]


def _pair(r: dict[str, Any]) -> dict[str, Any]:
    a, b = sorted((r["a"], r["b"]))
    return {"a": a, "b": b}


def _engine(r: dict[str, Any]) -> dict[str, Any]:
    return {"engine": r["engine"]}


def _sum_by(rows: Iterable[dict[str, Any]], key: Key) -> list[dict[str, Any]]:
    out: dict[tuple[Any, ...], dict[str, Any]] = {}
    for r in rows:
        ids = key(r)
        t = out.setdefault(tuple(ids.values()), ids)
        for k, v in r.items():
            if k != "ts" and k not in ids:
                t[k] = t.get(k, 0) + v
    return list(out.values())


def independence_totals(
    overlap: list[dict[str, Any]], uniqueness: list[dict[str, Any]], *, since: str = ""
) -> dict[str, list[dict[str, Any]]]:
    unique_since = max(since, UNIQUENESS_START)
    return {
        "overlap": _sum_by((r for r in overlap if r["ts"] >= since), _pair),
        "uniqueness": _sum_by((r for r in uniqueness if r["ts"] >= unique_since), _engine),
    }


def _compact(rows: list[dict[str, Any]], key: Key, day: str) -> list[dict[str, Any]]:
    old = (r for r in rows if r["ts"][:10] < day)
    daily = _sum_by(old, lambda r: {"ts": r["ts"][:10] + "T00:00Z", **key(r)})
    return daily + [r for r in rows if r["ts"][:10] >= day]


def compact_daily(
    overlap: list[dict[str, Any]], uniqueness: list[dict[str, Any]], *, before: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return _compact(overlap, _pair, before[:10]), _compact(uniqueness, _engine, before[:10])
