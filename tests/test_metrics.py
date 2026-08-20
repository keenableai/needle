import math

import pytest

from keenbench.shared.metrics import (
    NDCG_K,
    apply_redundancy_penalties,
    dcg_at_k,
    gain,
    normalize_url,
    oracle_order,
)


def test_gain_mapping():
    assert gain(4) == 1.0
    assert gain(3) == 0.667
    assert gain(2) == 0.117
    assert gain(1) == 0.0
    assert gain(0) == 0.0


def test_dcg_all_perfect_hits_the_ceiling():
    ceiling = sum(1.0 / math.log2(i + 2) for i in range(NDCG_K))
    assert dcg_at_k([4, 4, 4, 4, 4]) == pytest.approx(ceiling)


def test_dcg_top_rank_weighted_more():
    top = dcg_at_k([4, 0, 0, 0, 0])
    bottom = dcg_at_k([0, 0, 0, 0, 4])
    assert top > bottom
    assert top == pytest.approx(1.0)


def test_dcg_truncates_at_k():
    assert dcg_at_k([4, 4, 4, 4, 4, 4], k=5) == dcg_at_k([4, 4, 4, 4, 4], k=5)


def test_dcg_empty_is_zero():
    assert dcg_at_k([]) == 0.0


def test_normalize_url():
    assert normalize_url("https://www.Example.com/a/") == "example.com/a"
    assert normalize_url("http://example.com/a") == "example.com/a"
    assert normalize_url("https://example.com:443/a") == "example.com/a"
    assert normalize_url("https://example.com/a?x=1#frag") == "example.com/a?x=1"
    assert normalize_url("https://example.com/") == "example.com"
    assert normalize_url("https://example.com/a?x=1") != normalize_url("https://example.com/a?x=2")


def test_normalize_url_query_params():
    assert normalize_url("https://a.com/p?b=2&a=1") == normalize_url("https://a.com/p?a=1&b=2")
    assert normalize_url("https://a.com/p?utm_source=x&gclid=y&a=1") == "a.com/p?a=1"
    assert normalize_url("https://a.com/p?msockid=x&srsltid=y&twclid=z") == "a.com/p"
    assert normalize_url("https://a.com/p?utm_source=x") == "a.com/p"
    assert normalize_url("https://a.com/p?a=1") != normalize_url("https://a.com/p")


def test_normalize_url_percent_encoding():
    assert normalize_url("https://a.com/caf%C3%A9") == normalize_url("https://a.com/café")
    assert normalize_url("https://a.com/p?q=a%20b") == normalize_url("https://a.com/p?q=a+b")


def test_penalties_duplicate_url_only():
    urls = [
        "https://a.com/1",
        "https://a.com/2",
        "https://a.com/3",
        "https://b.com/1",
        "https://a.com/1",
    ]
    out = apply_redundancy_penalties(urls, [4, 4, 4, 4, 4])
    assert out == [4, 4, 4, 4, 0]


def test_penalties_url_variants_count_as_duplicates():
    urls = ["https://a.com/1", "http://www.a.com/1/"]
    assert apply_redundancy_penalties(urls, [4, 4]) == [4, 0]


def test_penalties_floor_at_zero():
    assert apply_redundancy_penalties(["https://a.com/1", "https://a.com/1"], [4, 3]) == [4, 0]


def test_penalties_site_queries_exempt():
    urls = ["https://a.com/1", "https://a.com/2", "https://a.com/1"]
    ratings = [4, 4, 4]
    assert apply_redundancy_penalties(urls, ratings, query_text="site:a.com docs") == ratings


def test_penalties_website_word_not_exempt():
    urls = ["https://a.com/1", "https://a.com/1"]
    assert apply_redundancy_penalties(urls, [4, 4], query_text="acme website: details") == [4, 0]


def test_oracle_order_sorts_by_rating():
    assert oracle_order([2, 4, 3]) == [1, 2, 0]
    assert oracle_order([3, 4, 4]) == [1, 2, 0]
