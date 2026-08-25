from needle.shared.overlap import overlap_rows, uniqueness_rows


def _report(per_query_by_engine):
    return {"engines": {name: {"per_query": pqs} for name, pqs in per_query_by_engine.items()}}


def _pq(urls, error=None):
    return {"search_error": error, "results": [{"url": u} for u in urls]}


def test_overlap_rows_pairs():
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
    assert r12["num_queries"] == 2
    assert r12["ts"] == "2026-07-02T10:00Z"


def test_overlap_skips_errors_and_double_empty():
    report = _report(
        {
            "e1": [_pq(["https://a.com"]), _pq([]), _pq(["https://a.com"])],
            "e2": [_pq([], error={"error_type": "transport"}), _pq([]), _pq(["https://a.com"])],
        }
    )
    (row,) = overlap_rows(report, ts="t")
    assert row["num_queries"] == 1


def test_overlap_url_normalization_joins_variants():
    report = _report(
        {
            "e1": [_pq_labeled([("https://www.a.com/x/", "SM")])],
            "e2": [_pq_labeled([("http://a.com/x", "FailsM")])],
        }
    )
    (row,) = overlap_rows(report, ts="t")
    assert row["low_shared_urls"] == 1
    assert row["num_suspect"] == 1


def test_uniqueness_rows():
    report = _report(
        {
            "e1": [_pq(["https://a.com", "https://b.com"]), _pq(["https://x.com"])],
            "e2": [_pq(["https://www.a.com/"]), _pq(["https://y.com"])],
            "e3": [_pq(["https://c.com"]), _pq([], error={"error_type": "transport"})],
        }
    )
    by_engine = {r["engine"]: r for r in uniqueness_rows(report, ts="t")}
    assert by_engine["e1"] == {
        "ts": "t",
        "engine": "e1",
        "unique_urls": 2,
        "total_urls": 3,
        "unique_relevant_urls": 0,
    }
    assert by_engine["e2"] == {
        "ts": "t",
        "engine": "e2",
        "unique_urls": 1,
        "total_urls": 2,
        "unique_relevant_urls": 0,
    }
    assert by_engine["e3"] == {
        "ts": "t",
        "engine": "e3",
        "unique_urls": 1,
        "total_urls": 1,
        "unique_relevant_urls": 0,
    }


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
        "unique_relevant_urls": 0,
    }


def test_uniqueness_ignores_same_family_engines():
    report = _report(
        {
            "exa": [_pq(["https://a.com", "https://b.com"])],
            "exa-instant": [_pq(["https://a.com"])],
            "google": [_pq(["https://b.com"])],
        }
    )
    by_engine = {r["engine"]: r for r in uniqueness_rows(report, ts="t")}
    assert by_engine["exa"]["unique_urls"] == 1
    assert by_engine["exa"]["total_urls"] == 2
    assert by_engine["exa-instant"]["unique_urls"] == 1
    assert by_engine["google"]["unique_urls"] == 0


def test_uniqueness_skips_queries_with_only_family_engines():
    report = _report(
        {
            "exa": [_pq(["https://a.com"])],
            "exa-instant": [_pq(["https://a.com"])],
        }
    )
    by_engine = {r["engine"]: r for r in uniqueness_rows(report, ts="t")}
    assert by_engine["exa"]["total_urls"] == 0
    assert by_engine["exa-instant"]["total_urls"] == 0


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


def test_overlap_rows_suspect_counts_shared3_without_judgements():
    report = _report(
        {
            "e1": [_pq(["https://a.com", "https://b.com", "https://c.com"])],
            "e2": [_pq(["https://a.com", "https://b.com", "https://c.com"])],
        }
    )
    (row,) = overlap_rows(report, ts="t")
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
    assert by_engine["e1"]["unique_relevant_urls"] == 1
    assert by_engine["e2"]["unique_relevant_urls"] == 0


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
    assert by_engine["e1"]["unique_relevant_urls"] == 0
    assert by_engine["e2"]["unique_relevant_urls"] == 0
    assert by_engine["e3"]["unique_relevant_urls"] == 0


def test_uniqueness_counts_relevant_url_no_other_family_returned():
    report = _report(
        {
            "e1": [_pq_hit(["https://gold.com"], 1)],
            "e2": [_pq_hit(["https://other.com"], None)],
        }
    )
    by_engine = {r["engine"]: r for r in uniqueness_rows(report, ts="t")}
    assert by_engine["e1"]["unique_relevant_urls"] == 1
    assert by_engine["e2"]["unique_relevant_urls"] == 0


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
