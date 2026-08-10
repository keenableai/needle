import hashlib
from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeVar

T = TypeVar("T")

MASK64 = (1 << 64) - 1


def interleave(lists: list[list[T]]) -> list[T]:
    merged: list[T] = []
    for i in range(max((len(x) for x in lists), default=0)):
        for x in lists:
            if i < len(x):
                merged.append(x[i])
    return merged


def dedupe_by(items: list[T], key: Callable[[T], Any]) -> list[T]:
    seen: set[Any] = set()
    out: list[T] = []
    for item in items:
        k = key(item)
        if k not in seen:
            seen.add(k)
            out.append(item)
    return out


def shuffle_indices(n: int, seed: int) -> list[int]:
    indices = list(range(n))
    state = seed & MASK64
    for i in range(n - 1, 0, -1):
        state = (state + 0x9E3779B97F4A7C15) & MASK64
        z = state
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9 & MASK64
        z = (z ^ (z >> 27)) * 0x94D049BB133111EB & MASK64
        z = z ^ (z >> 31)
        j = z % (i + 1)
        indices[i], indices[j] = indices[j], indices[i]
    return indices


def sample_uniform(records: list[dict[str, Any]], k: int, seed: int) -> list[dict[str, Any]]:
    if k <= 0 or not records:
        return []
    perm = shuffle_indices(len(records), seed)
    return [records[i] for i in perm[:k]]


def sample_stratified(
    records: list[dict[str, Any]],
    k: int,
    seed: int,
    *,
    key: str | Callable[[dict[str, Any]], str] = "topical_domain",
) -> list[dict[str, Any]]:
    if k <= 0 or not records:
        return []

    key_fn = key if callable(key) else (lambda r: str(r.get(key) or ""))
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        by_domain.setdefault(key_fn(r), []).append(r)

    for d, rs in by_domain.items():
        domain_seed = seed ^ int.from_bytes(hashlib.sha256(d.encode()).digest()[:8], "big")
        perm = shuffle_indices(len(rs), domain_seed)
        by_domain[d] = [rs[i] for i in perm]

    domains = sorted(by_domain.keys())
    perm = shuffle_indices(len(domains), seed)
    domain_order = [domains[i] for i in perm]

    picked: list[dict[str, Any]] = []
    while len(picked) < k and domain_order:
        next_round: list[str] = []
        for d in domain_order:
            if len(picked) >= k:
                break
            bucket = by_domain[d]
            if not bucket:
                continue
            picked.append(bucket.pop(0))
            if bucket:
                next_round.append(d)
        domain_order = next_round
    return picked


def sample(
    records: list[dict[str, Any]],
    k: int,
    seed: int,
    *,
    strategy: str,
    key: str | Callable[[dict[str, Any]], str] = "topical_domain",
) -> list[dict[str, Any]]:
    if strategy == "head":
        return records[:k]
    if strategy == "uniform":
        return sample_uniform(records, k, seed)
    if strategy == "stratified":
        return sample_stratified(records, k, seed, key=key)
    raise ValueError(f"unknown sample strategy {strategy!r} (known: stratified, uniform, head)")


def seed_from_hour_ts(hour_ts: datetime) -> int:
    digest = hashlib.sha256(hour_ts.isoformat().encode()).digest()
    return int.from_bytes(digest[:8], "big")
