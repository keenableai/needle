from typing import Any

from keenbench.shared.metrics import normalize_url
from keenbench.shared.recall import ULTIMATE

TS_FMT = "%Y-%m-%dT%H:%MZ"


GOOD_LABELS = frozenset({"HM", "FullyM"})


def _url_sets(report: dict[str, Any]) -> dict[str, list[set[str] | None]]:
    return {
        name: [
            None
            if pq["search_error"] is not None
            else {normalize_url(r["url"]) for r in pq["results"]}
            for pq in e["per_query"]
        ]
        for name, e in report["engines"].items()
        if name != ULTIMATE
    }


def _low_url_sets(report: dict[str, Any]) -> dict[str, list[set[str] | None]]:
    return {
        name: [
            None
            if pq["search_error"] is not None
            else {
                normalize_url(r["url"])
                for r in pq["results"]
                if r.get("label") and r["label"] not in GOOD_LABELS
            }
            for pq in e["per_query"]
        ]
        for name, e in report["engines"].items()
        if name != ULTIMATE
    }


def _relevant_urls(pq: dict[str, Any]) -> set[str]:
    urls = {normalize_url(r["url"]) for r in pq["results"] if r.get("label") in GOOD_LABELS}
    if pq.get("hit_rank") is not None:
        urls.add(normalize_url(pq["results"][pq["hit_rank"] - 1]["url"]))
    return urls


def _relevant_url_sets(report: dict[str, Any]) -> dict[str, list[set[str] | None]]:
    return {
        name: [
            None if pq["search_error"] is not None else _relevant_urls(pq)
            for pq in e["per_query"]
        ]
        for name, e in report["engines"].items()
        if name != ULTIMATE
    }


def overlap_rows(report: dict[str, Any], *, ts: str) -> list[dict[str, Any]]:
    url_sets = _url_sets(report)
    low_sets = _low_url_sets(report)
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
    url_sets = _url_sets(report)
    rel_sets = _relevant_url_sets(report)
    rows = []
    for name, sets in url_sets.items():
        unique = total = rel_unique = rel_total = 0
        for i, s in enumerate(sets):
            if s is None:
                continue
            other_names = [n2 for n2, o in url_sets.items() if n2 != name and o[i] is not None]
            if not other_names:
                continue
            total += len(s)
            unique += len(s - set().union(*(url_sets[n2][i] for n2 in other_names)))
            rel = rel_sets[name][i]
            rel_total += len(rel)
            rel_unique += len(rel - set().union(*(rel_sets[n2][i] for n2 in other_names)))
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
