from keenbench.shared.overlap import normalize_url, overlap_rows


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
    assert normalize_url("https://a.com/p?utm_source=x") == "a.com/p"
    assert normalize_url("https://a.com/p?a=1") != normalize_url("https://a.com/p")


def test_normalize_url_percent_encoding():
    assert normalize_url("https://a.com/caf%C3%A9") == normalize_url("https://a.com/café")
    assert normalize_url("https://a.com/p?q=a%20b") == normalize_url("https://a.com/p?q=a+b")


def _report(per_query_by_engine):
    return {"engines": {name: {"per_query": pqs} for name, pqs in per_query_by_engine.items()}}


def _pq(urls, error=None):
    return {"search_error": error, "results": [{"url": u} for u in urls]}


def test_overlap_rows_jaccard_and_pairs():
    report = _report(
        {
            "e1": [_pq(["https://a.com", "https://b.com"]), _pq(["https://a.com"])],
            "e2": [_pq(["https://a.com", "https://c.com"]), _pq(["https://d.com"])],
            "e3": [_pq(["https://b.com/"]), _pq([])],
        }
    )
    rows = overlap_rows(report, ts="2026-07-02T10:00Z")
    by_pair = {(r["a"], r["b"]): r for r in rows}
    assert set(by_pair) == {("e1", "e2"), ("e1", "e3"), ("e2", "e3")}
    r12 = by_pair[("e1", "e2")]
    assert r12["jaccard_sum"] == round(1 / 3 + 0.0, 4)
    assert r12["num_queries"] == 2
    assert r12["ts"] == "2026-07-02T10:00Z"
    r13 = by_pair[("e1", "e3")]
    assert r13["jaccard_sum"] == 0.5
    assert r13["num_queries"] == 2


def test_overlap_skips_errors_and_double_empty():
    report = _report(
        {
            "e1": [_pq(["https://a.com"]), _pq([]), _pq(["https://a.com"])],
            "e2": [_pq([], error={"error_type": "transport"}), _pq([]), _pq(["https://a.com"])],
        }
    )
    (row,) = overlap_rows(report, ts="t")
    assert row["num_queries"] == 1
    assert row["jaccard_sum"] == 1.0


def test_overlap_url_normalization_joins_variants():
    report = _report(
        {
            "e1": [_pq(["https://www.a.com/x/"])],
            "e2": [_pq(["http://a.com/x"])],
        }
    )
    (row,) = overlap_rows(report, ts="t")
    assert row["jaccard_sum"] == 1.0
