import pytest

from keenbench.shared.metrics import (
    RBP_MAX,
    RBP_P,
    apply_redundancy_penalties,
    gain,
    rbp_at_k,
    url_domain,
)


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


def test_url_domain_is_lowercased_host():
    assert url_domain("https://WWW.Ex.com/path?q=1") == "www.ex.com"
    assert url_domain("not a url") == ""


def test_penalties_duplicate_url_and_domain_redundancy():
    urls = [
        "https://a.com/1",
        "https://a.com/2",
        "https://a.com/3",
        "https://b.com/1",
        "https://a.com/1",
    ]
    out = apply_redundancy_penalties(urls, [4, 4, 4, 4, 4])
    assert out == [4, 3, 2, 4, 0]


def test_penalties_floor_at_zero():
    assert apply_redundancy_penalties(["https://a.com/1", "https://a.com/2"], [4, 1]) == [4, 0]


def test_penalties_site_queries_exempt():
    urls = ["https://a.com/1", "https://a.com/2", "https://a.com/1"]
    ratings = [4, 4, 4]
    assert apply_redundancy_penalties(urls, ratings, query_text="site:a.com docs") == ratings
