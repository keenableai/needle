from collections.abc import Sequence

RBP_P = 0.8
RBP_K = 5

_GAIN = {4: 1.0, 3: 0.667, 2: 0.117, 1: 0.0, 0: 0.0}

RBP_MAX = 1.0 - RBP_P**RBP_K


def gain(rating: int) -> float:
    return _GAIN.get(rating, 0.0)


def rbp_at_k(ratings: Sequence[int], *, p: float = RBP_P, k: int = RBP_K) -> float:
    return (1.0 - p) * sum(gain(r) * p**i for i, r in enumerate(ratings[:k]))
