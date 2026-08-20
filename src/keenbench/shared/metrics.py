import math
import re
from collections.abc import Sequence
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

NDCG_K = 5

TRACKING_PARAMS = {
    "_hsenc",
    "_hsmi",
    "dclid",
    "epik",
    "fbclid",
    "gbraid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "mkt_tok",
    "msclkid",
    "msockid",
    "oly_anon_id",
    "oly_enc_id",
    "srsltid",
    "ttclid",
    "twclid",
    "vero_id",
    "wbraid",
    "yclid",
}

GAIN = {4: 1.0, 3: 0.667, 2: 0.117, 1: 0.0, 0: 0.0}

DUPLICATE_URL_PENALTY = 4

SITE_OPERATOR_RE = re.compile(r"\bsite:")


def gain(rating: int) -> float:
    return GAIN.get(rating, 0.0)


def normalize_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url
    host = (parts.hostname or "").removeprefix("www.")
    path = unquote(parts.path).rstrip("/")
    params = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not (k.startswith("utm_") or k in TRACKING_PARAMS)
    )
    query = f"?{urlencode(params)}" if params else ""
    return f"{host}{path}{query}"


def apply_redundancy_penalties(
    urls: Sequence[str], ratings: Sequence[int], *, query_text: str = ""
) -> list[int]:
    if SITE_OPERATOR_RE.search(query_text.lower()):
        return list(ratings)
    seen_urls: set[str] = set()
    out: list[int] = []
    for url, rating in zip(urls, ratings, strict=True):
        canonical = normalize_url(url)
        penalty = DUPLICATE_URL_PENALTY if canonical in seen_urls else 0
        out.append(max(0, rating - penalty))
        seen_urls.add(canonical)
    return out


def dcg_at_k(ratings: Sequence[int], *, k: int = NDCG_K) -> float:
    return sum(gain(r) / math.log2(i + 2) for i, r in enumerate(ratings[:k]))


def oracle_order(ratings: Sequence[int]) -> list[int]:
    return sorted(range(len(ratings)), key=lambda i: -ratings[i])
