from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

TS_FMT = "%Y-%m-%dT%H:%MZ"
WINDOW_HOURS = 24
TRACKING_PARAMS = {"gclid", "fbclid", "msclkid", "yclid", "igshid", "mc_cid", "mc_eid"}


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").removeprefix("www.")
    path = unquote(parts.path).rstrip("/")
    params = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not (k.startswith("utm_") or k in TRACKING_PARAMS)
    )
    query = f"?{urlencode(params)}" if params else ""
    return f"{host}{path}{query}"


def _url_sets(report: dict[str, Any]) -> dict[str, list[set[str] | None]]:
    return {
        name: [
            None
            if pq["search_error"] is not None
            else {normalize_url(r["url"]) for r in pq["results"]}
            for pq in e["per_query"]
        ]
        for name, e in report["engines"].items()
    }


def overlap_rows(report: dict[str, Any], *, ts: str) -> list[dict[str, Any]]:
    url_sets = _url_sets(report)
    names = list(url_sets)
    rows = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            jaccard_sum = 0.0
            shared3 = 0
            n = 0
            for sa, sb in zip(url_sets[a], url_sets[b], strict=True):
                if sa is None or sb is None or not (sa or sb):
                    continue
                jaccard_sum += len(sa & sb) / len(sa | sb)
                shared3 += len(sa & sb) >= 3
                n += 1
            rows.append(
                {
                    "ts": ts,
                    "a": a,
                    "b": b,
                    "jaccard_sum": round(jaccard_sum, 4),
                    "num_shared3": shared3,
                    "num_queries": n,
                }
            )
    return rows


def uniqueness_rows(report: dict[str, Any], *, ts: str) -> list[dict[str, Any]]:
    url_sets = _url_sets(report)
    rows = []
    for name, sets in url_sets.items():
        unique = 0
        total = 0
        for i, s in enumerate(sets):
            if s is None:
                continue
            others = [s2 for n2, o in url_sets.items() if n2 != name and (s2 := o[i]) is not None]
            if not others:
                continue
            total += len(s)
            unique += len(s - set().union(*others))
        rows.append({"ts": ts, "engine": name, "unique_urls": unique, "total_urls": total})
    return rows
