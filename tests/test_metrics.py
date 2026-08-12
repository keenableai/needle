import pytest

from keenbench.shared.metrics import (
    RBP_K,
    RBP_P,
    apply_redundancy_penalties,
    gain,
    normalize_url,
    oracle_order,
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
    assert rbp_at_k([4, 4, 4, 4, 4]) == pytest.approx(1.0 - RBP_P**RBP_K)


def test_rbp_top_rank_weighted_more():
    top = rbp_at_k([4, 0, 0, 0, 0])
    bottom = rbp_at_k([0, 0, 0, 0, 4])
    assert top > bottom
    assert top == pytest.approx((1 - RBP_P) * 1.0)


def test_rbp_truncates_at_k():
    assert rbp_at_k([4, 4, 4, 4, 4, 4], k=5) == rbp_at_k([4, 4, 4, 4, 4], k=5)


def test_rbp_empty_is_zero():
    assert rbp_at_k([]) == 0.0


def test_url_domain_is_lowercased_host_without_www():
    assert url_domain("https://WWW.Ex.com/path?q=1") == "ex.com"
    assert url_domain("https://ex.com/path") == "ex.com"
    assert url_domain("not a url") == ""


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


def test_penalties_url_variants_count_as_duplicates():
    urls = ["https://a.com/1", "http://www.a.com/1/"]
    assert apply_redundancy_penalties(urls, [4, 4]) == [4, 0]


def test_penalties_floor_at_zero():
    assert apply_redundancy_penalties(["https://a.com/1", "https://a.com/2"], [4, 1]) == [4, 0]


def test_penalties_site_queries_exempt():
    urls = ["https://a.com/1", "https://a.com/2", "https://a.com/1"]
    ratings = [4, 4, 4]
    assert apply_redundancy_penalties(urls, ratings, query_text="site:a.com docs") == ratings


def test_penalties_website_word_not_exempt():
    urls = ["https://a.com/1", "https://a.com/1"]
    assert apply_redundancy_penalties(urls, [4, 4], query_text="acme website: details") == [4, 0]


def test_oracle_order_sorts_by_rating():
    urls = ["https://a.com/1", "https://b.com/1", "https://c.com/1"]
    assert oracle_order(urls, [2, 4, 3]) == [1, 2, 0]


def test_oracle_order_defers_repeated_domains():
    urls = ["https://a.com/1", "https://a.com/2", "https://a.com/3", "https://b.com/1"]
    order = oracle_order(urls, [4, 4, 4, 3])
    assert order == [0, 1, 3, 2]
    ordered_urls = [urls[i] for i in order]
    ordered_ratings = [[4, 4, 4, 3][i] for i in order]
    assert apply_redundancy_penalties(ordered_urls, ordered_ratings) == [4, 3, 3, 2]


def test_oracle_order_site_queries_keep_rating_order():
    urls = ["https://a.com/1", "https://a.com/2", "https://a.com/3"]
    assert oracle_order(urls, [3, 4, 4], query_text="site:a.com docs") == [1, 2, 0]
