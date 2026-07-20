import re
from collections.abc import Sequence
from urllib.parse import urlsplit

RBP_P = 0.8
RBP_K = 5

GAIN = {4: 1.0, 3: 0.667, 2: 0.117, 1: 0.0, 0: 0.0}

RBP_MAX = 1.0 - RBP_P**RBP_K

DUPLICATE_URL_PENALTY = 4
PARTIAL_DOMAIN_PENALTY = 1
FULL_DOMAIN_PENALTY = 2

SITE_OPERATOR_RE = re.compile(r"\bsite:")


def gain(rating: int) -> float:
    return GAIN.get(rating, 0.0)


def url_domain(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _domain_penalty(prior_same_domain: int) -> int:
    if prior_same_domain >= 2:
        return FULL_DOMAIN_PENALTY
    if prior_same_domain == 1:
        return PARTIAL_DOMAIN_PENALTY
    return 0


def apply_redundancy_penalties(
    urls: Sequence[str], ratings: Sequence[int], *, query_text: str = ""
) -> list[int]:
    if SITE_OPERATOR_RE.search(query_text.lower()):
        return list(ratings)
    seen_urls: set[str] = set()
    domain_counts: dict[str, int] = {}
    out: list[int] = []
    for url, rating in zip(urls, ratings, strict=True):
        domain = url_domain(url)
        prior_same_domain = domain_counts.get(domain, 0)
        penalty = DUPLICATE_URL_PENALTY if url in seen_urls else _domain_penalty(prior_same_domain)
        out.append(max(0, rating - penalty))
        seen_urls.add(url)
        domain_counts[domain] = prior_same_domain + 1
    return out


def rbp_at_k(ratings: Sequence[int], *, p: float = RBP_P, k: int = RBP_K) -> float:
    return (1.0 - p) * sum(gain(r) * p**i for i, r in enumerate(ratings[:k]))


def oracle_order(urls: Sequence[str], ratings: Sequence[int], *, query_text: str = "") -> list[int]:
    remaining = sorted(range(len(urls)), key=lambda i: -ratings[i])
    if SITE_OPERATOR_RE.search(query_text.lower()):
        return remaining
    domains = [url_domain(u) for u in urls]
    picked: list[int] = []
    domain_counts: dict[str, int] = {}

    def penalized(i: int) -> int:
        return max(0, ratings[i] - _domain_penalty(domain_counts.get(domains[i], 0)))

    while remaining:
        best = max(remaining, key=penalized)
        remaining.remove(best)
        picked.append(best)
        domain_counts[domains[best]] = domain_counts.get(domains[best], 0) + 1
    return picked
