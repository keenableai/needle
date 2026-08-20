from collections.abc import Callable
from typing import Any

from needle.shared.metrics import normalize_url
from needle.shared.recall import ULTIMATE

TS_FMT = "%Y-%m-%dT%H:%MZ"


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
    "parallel-turbo": "parallel",
}


def _all_urls(pq: dict[str, Any]) -> set[str]:
    return {normalize_url(r["url"]) for r in pq["results"]}


def _low_urls(pq: dict[str, Any]) -> set[str]:
    return {
        normalize_url(r["url"])
        for r in pq["results"]
        if r.get("label") and r["label"] not in GOOD_LABELS
    }


def _urls_with_relevant(pq: dict[str, Any]) -> tuple[set[str], set[str]]:
    urls: set[str] = set()
    relevant: set[str] = set()
    for rank, r in enumerate(pq["results"], start=1):
        url = normalize_url(r["url"])
        urls.add(url)
        if r.get("label") in GOOD_LABELS or rank == pq.get("hit_rank"):
            relevant.add(url)
    return urls, relevant


def overlap_rows(report: dict[str, Any], *, ts: str) -> list[dict[str, Any]]:
    url_sets = _engine_sets(report, _all_urls)
    low_sets = _engine_sets(report, _low_urls)
    names = list(url_sets)
    rows = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            jaccard_sum = 0.0
            shared3 = 0
            suspect = 0
            low_shared_urls = 0
            n = 0
            for qi, (sa, sb) in enumerate(zip(url_sets[a], url_sets[b], strict=True)):
                if sa is None or sb is None or not (sa or sb):
                    continue
                jaccard_sum += len(sa & sb) / len(sa | sb)
                shared3 += len(sa & sb) >= 3
                low = (low_sets[a][qi] or set()) & (low_sets[b][qi] or set())
                low_shared_urls += len(low)
                suspect += len(low) >= 1 or len(sa & sb) >= 3
                n += 1
            rows.append(
                {
                    "ts": ts,
                    "a": a,
                    "b": b,
                    "jaccard_sum": round(jaccard_sum, 4),
                    "num_shared3": shared3,
                    "num_suspect": suspect,
                    "low_shared_urls": low_shared_urls,
                    "num_queries": n,
                }
            )
    return rows


def uniqueness_rows(report: dict[str, Any], *, ts: str) -> list[dict[str, Any]]:
    url_sets = _engine_sets(report, _urls_with_relevant)
    rows = []
    for name, sets in url_sets.items():
        unique = total = rel_unique = rel_total = 0
        for i, pair in enumerate(sets):
            if pair is None:
                continue
            others = [
                p
                for n2, o in url_sets.items()
                if FAMILIES.get(n2, n2) != FAMILIES.get(name, name) and (p := o[i]) is not None
            ]
            if not others:
                continue
            s, rel = pair
            total += len(s)
            unique += len(s - set().union(*(p[0] for p in others)))
            rel_total += len(rel)
            if rel:
                rel_unique += len(rel - set().union(*(p[1] for p in others)))
        rows.append(
            {
                "ts": ts,
                "engine": name,
                "unique_urls": unique,
                "total_urls": total,
                "relevant_unique_urls": rel_unique,
                "relevant_total_urls": rel_total,
            }
        )
    return rows
