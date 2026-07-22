from keenbench.shared.overlap import overlap_rows, uniqueness_rows


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


def test_overlap_num_shared3():
    shared = ["https://a.com", "https://b.com", "https://c.com"]
    report = _report(
        {
            "e1": [_pq(shared + ["https://d.com"]), _pq(["https://a.com", "https://b.com"])],
            "e2": [_pq(shared + ["https://e.com"]), _pq(["https://a.com", "https://b.com"])],
        }
    )
    (row,) = overlap_rows(report, ts="t")
    assert row["num_shared3"] == 1
    assert row["num_queries"] == 2


def test_uniqueness_rows():
    report = _report(
        {
            "e1": [_pq(["https://a.com", "https://b.com"]), _pq(["https://x.com"])],
            "e2": [_pq(["https://www.a.com/"]), _pq(["https://y.com"])],
            "e3": [_pq(["https://c.com"]), _pq([], error={"error_type": "transport"})],
        }
    )
    by_engine = {r["engine"]: r for r in uniqueness_rows(report, ts="t")}
    empty_rel = {"relevant_unique_urls": 0, "relevant_total_urls": 0}
    assert by_engine["e1"] == {"ts": "t", "engine": "e1", "unique_urls": 2, "total_urls": 3, **empty_rel}
    assert by_engine["e2"] == {"ts": "t", "engine": "e2", "unique_urls": 1, "total_urls": 2, **empty_rel}
    assert by_engine["e3"] == {"ts": "t", "engine": "e3", "unique_urls": 1, "total_urls": 1, **empty_rel}


def test_uniqueness_skips_queries_with_no_other_engine():
    report = _report(
        {
            "e1": [_pq(["https://a.com"])],
            "e2": [_pq([], error={"error_type": "transport"})],
        }
    )
    by_engine = {r["engine"]: r for r in uniqueness_rows(report, ts="t")}
    assert by_engine["e1"] == {
        "ts": "t",
        "engine": "e1",
        "unique_urls": 0,
        "total_urls": 0,
        "relevant_unique_urls": 0,
        "relevant_total_urls": 0,
    }


def _pq_labeled(url_labels, error=None):
    return {
        "search_error": error,
        "results": [{"url": u, "label": lab} for u, lab in url_labels],
    }


def test_overlap_rows_low_relevance_sharing():
    report = _report(
        {
            "e1": [
                _pq_labeled(
                    [
                        ("https://junk1.com", "SM"),
                        ("https://junk2.com", "FailsM"),
                        ("https://good.com", "FullyM"),
                    ]
                )
            ],
            "e2": [
                _pq_labeled(
                    [
                        ("https://junk1.com", "MM"),
                        ("https://junk2.com", "SM"),
                        ("https://good.com", "HM"),
                    ]
                )
            ],
            "e3": [_pq_labeled([("https://good.com", "FullyM"), ("https://junk1.com", "HM")])],
        }
    )
    rows = overlap_rows(report, ts="t")
    by_pair = {(r["a"], r["b"]): r for r in rows}
    r12 = by_pair[("e1", "e2")]
    assert r12["low_shared_urls"] == 2
    assert r12["num_suspect"] == 1
    r13 = by_pair[("e1", "e3")]
    assert r13["low_shared_urls"] == 0
    assert r13["num_suspect"] == 0


def test_overlap_rows_low_relevance_ignores_unjudged():
    report = _report(
        {
            "e1": [_pq(["https://a.com", "https://b.com"])],
            "e2": [_pq(["https://a.com", "https://b.com"])],
        }
    )
    (row,) = overlap_rows(report, ts="t")
    assert row["low_shared_urls"] == 0
    assert row["num_suspect"] == 0
    assert row["num_shared3"] == 0


def test_overlap_rows_suspect_counts_shared3_without_judgements():
    report = _report(
        {
            "e1": [_pq(["https://a.com", "https://b.com", "https://c.com"])],
            "e2": [_pq(["https://a.com", "https://b.com", "https://c.com"])],
        }
    )
    (row,) = overlap_rows(report, ts="t")
    assert row["num_shared3"] == 1
    assert row["num_suspect"] == 1
    assert row["low_shared_urls"] == 0


def test_overlap_rows_suspect_counts_single_shared_low_url():
    report = _report(
        {
            "e1": [_pq_labeled([("https://junk.com", "SM"), ("https://good.com", "FullyM")])],
            "e2": [_pq_labeled([("https://junk.com", "FailsM"), ("https://other.com", "HM")])],
        }
    )
    (row,) = overlap_rows(report, ts="t")
    assert row["num_suspect"] == 1
    assert row["low_shared_urls"] == 1


def test_uniqueness_relevant_only_by_label():
    report = _report(
        {
            "e1": [
                _pq_labeled(
                    [
                        ("https://good1.com", "FullyM"),
                        ("https://good2.com", "HM"),
                        ("https://junk.com", "SM"),
                    ]
                )
            ],
            "e2": [_pq_labeled([("https://good1.com", "HM"), ("https://junk.com", "FullyM")])],
        }
    )
    by_engine = {r["engine"]: r for r in uniqueness_rows(report, ts="t")}
    r1 = by_engine["e1"]
    assert r1["relevant_total_urls"] == 2
    assert r1["relevant_unique_urls"] == 1
    r2 = by_engine["e2"]
    assert r2["relevant_total_urls"] == 2
    assert r2["relevant_unique_urls"] == 1


def _pq_hit(urls, hit_rank):
    return dict(_pq(urls), hit_rank=hit_rank)


def test_uniqueness_relevant_only_by_hit_rank():
    report = _report(
        {
            "e1": [_pq_hit(["https://miss.com", "https://gold.com"], 2)],
            "e2": [_pq_hit(["https://gold.com"], 1)],
            "e3": [_pq_hit(["https://other.com"], None)],
        }
    )
    by_engine = {r["engine"]: r for r in uniqueness_rows(report, ts="t")}
    assert by_engine["e1"]["relevant_total_urls"] == 1
    assert by_engine["e1"]["relevant_unique_urls"] == 0
    assert by_engine["e2"]["relevant_total_urls"] == 1
    assert by_engine["e2"]["relevant_unique_urls"] == 0
    assert by_engine["e3"]["relevant_total_urls"] == 0
    assert by_engine["e3"]["relevant_unique_urls"] == 0


def test_overlap_and_uniqueness_exclude_ultimate():
    report = _report(
        {
            "e1": [_pq(["https://a.com"])],
            "e2": [_pq(["https://b.com"])],
            "ultimate": [_pq(["https://a.com", "https://b.com"])],
        }
    )
    rows = overlap_rows(report, ts="t")
    assert {(r["a"], r["b"]) for r in rows} == {("e1", "e2")}
    urows = uniqueness_rows(report, ts="t")
    assert {r["engine"] for r in urows} == {"e1", "e2"}
    assert all(r["unique_urls"] == 1 for r in urows)
