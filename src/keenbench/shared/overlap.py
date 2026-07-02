from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

TRACKING_PARAMS = {"gclid", "fbclid", "msclkid", "yclid", "igshid", "mc_cid", "mc_eid"}


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = parts.netloc.rpartition("@")[2].lower()
    host = host.removesuffix(":80").removesuffix(":443").removeprefix("www.")
    path = unquote(parts.path).rstrip("/")
    params = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not (k.startswith("utm_") or k in TRACKING_PARAMS)
    )
    query = f"?{urlencode(params)}" if params else ""
    return f"{host}{path}{query}"


def overlap_rows(report: dict[str, Any], *, ts: str, bench: str) -> list[dict[str, Any]]:
    per_query = {name: e["per_query"] for name, e in report["engines"].items()}
    names = list(per_query)
    rows = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            jaccard_sum = 0.0
            n = 0
            for pa, pb in zip(per_query[a], per_query[b], strict=True):
                if pa["search_error"] is not None or pb["search_error"] is not None:
                    continue
                urls_a = {normalize_url(r["url"]) for r in pa["results"]}
                urls_b = {normalize_url(r["url"]) for r in pb["results"]}
                if not (urls_a or urls_b):
                    continue
                jaccard_sum += len(urls_a & urls_b) / len(urls_a | urls_b)
                n += 1
            rows.append(
                {
                    "ts": ts,
                    "bench": bench,
                    "a": a,
                    "b": b,
                    "jaccard_sum": round(jaccard_sum, 4),
                    "num_queries": n,
                }
            )
    return rows
