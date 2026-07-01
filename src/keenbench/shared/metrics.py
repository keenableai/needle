from collections.abc import Sequence

RBP_P = 0.8
RBP_K = 5

# Needs-Met rating -> RBP gain (keenable-eval GAIN_CASE).
_GAIN = {4: 1.0, 3: 0.667, 2: 0.117, 1: 0.0, 0: 0.0}

# RBP@k ceiling with gain <= 1: sum cut at rank k gives max 1 - p^k.
RBP_MAX = 1.0 - RBP_P**RBP_K


def gain(rating: int) -> float:
    return _GAIN.get(rating, 0.0)


def rbp_at_k(ratings: Sequence[int], *, p: float = RBP_P, k: int = RBP_K) -> float:
    """Rank-Biased Precision over ``ratings`` given in rank order (rank 1 first).

    ``(1 - p) * sum_{i<k} gain(rating_i) * p^i``. Does not apply the
    domain-redundancy penalties from the SQL kernel — plain gain-weighted RBP.
    """
    return (1.0 - p) * sum(gain(r) * p**i for i, r in enumerate(ratings[:k]))
