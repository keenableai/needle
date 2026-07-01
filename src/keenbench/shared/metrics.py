from collections.abc import Sequence
from urllib.parse import urlsplit

RBP_P = 0.8
RBP_K = 5

_GAIN = {4: 1.0, 3: 0.667, 2: 0.117, 1: 0.0, 0: 0.0}

RBP_MAX = 1.0 - RBP_P**RBP_K

# Domain-redundancy penalties, ported from keenable-eval's shared/rbp_kernel.py.
DUPLICATE_URL_PENALTY = 4
PARTIAL_DOMAIN_PENALTY = 1
FULL_DOMAIN_PENALTY = 2


def gain(rating: int) -> float:
    return _GAIN.get(rating, 0.0)


def url_domain(url: str) -> str:
    # Parity with the kernel's LOWER(NET.HOST(url)) — plain host, no eTLD+1 folding.
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def apply_redundancy_penalties(
    urls: Sequence[str], ratings: Sequence[int], *, query_text: str = ""
) -> list[int]:
    """Knock down ratings of repeated URLs/domains in rank order.

    Mirrors the ``penalized`` CTE in keenable-eval's rbp_kernel: duplicate URL
    -4, third-or-later result from a domain -2, second -1, floored at 0;
    ``site:`` queries are exempt (repetition is the point). The kernel's
    reasoning-text exemptions only fire on rating 0, where every branch yields
    0 anyway, so they are not ported.
    """
    if "site:" in query_text.lower():
        return list(ratings)
    seen_urls: set[str] = set()
    domain_counts: dict[str, int] = {}
    out: list[int] = []
    for url, rating in zip(urls, ratings, strict=True):
        domain = url_domain(url)
        prior_same_domain = domain_counts.get(domain, 0)
        if url in seen_urls:
            rating = max(0, rating - DUPLICATE_URL_PENALTY)
        elif prior_same_domain >= 2:
            rating = max(0, rating - FULL_DOMAIN_PENALTY)
        elif prior_same_domain == 1:
            rating = max(0, rating - PARTIAL_DOMAIN_PENALTY)
        out.append(rating)
        seen_urls.add(url)
        domain_counts[domain] = prior_same_domain + 1
    return out


def rbp_at_k(ratings: Sequence[int], *, p: float = RBP_P, k: int = RBP_K) -> float:
    return (1.0 - p) * sum(gain(r) * p**i for i, r in enumerate(ratings[:k]))
