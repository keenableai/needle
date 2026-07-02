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


def overlap_rows(report: dict[str, Any], *, ts: str) -> list[dict[str, Any]]:
    url_sets = {
        name: [
            None
            if pq["search_error"] is not None
            else {normalize_url(r["url"]) for r in pq["results"]}
            for pq in e["per_query"]
        ]
        for name, e in report["engines"].items()
    }
    names = list(url_sets)
    rows = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            jaccard_sum = 0.0
            n = 0
            for sa, sb in zip(url_sets[a], url_sets[b], strict=True):
                if sa is None or sb is None or not (sa or sb):
                    continue
                jaccard_sum += len(sa & sb) / len(sa | sb)
                n += 1
            rows.append(
                {"ts": ts, "a": a, "b": b, "jaccard_sum": round(jaccard_sum, 4), "num_queries": n}
            )
    return rows
