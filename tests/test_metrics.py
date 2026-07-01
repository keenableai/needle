import pytest

from keenbench.shared.metrics import RBP_MAX, RBP_P, gain, rbp_at_k


def test_gain_mapping():
    assert gain(4) == 1.0
    assert gain(3) == 0.667
    assert gain(2) == 0.117
    assert gain(1) == 0.0
    assert gain(0) == 0.0


def test_rbp_all_perfect_hits_the_ceiling():
    assert rbp_at_k([4, 4, 4, 4, 4]) == pytest.approx(RBP_MAX)


def test_rbp_top_rank_weighted_more():
    top = rbp_at_k([4, 0, 0, 0, 0])
    bottom = rbp_at_k([0, 0, 0, 0, 4])
    assert top > bottom
    assert top == pytest.approx((1 - RBP_P) * 1.0)


def test_rbp_truncates_at_k():
    assert rbp_at_k([4, 4, 4, 4, 4, 4], k=5) == rbp_at_k([4, 4, 4, 4, 4], k=5)


def test_rbp_empty_is_zero():
    assert rbp_at_k([]) == 0.0
