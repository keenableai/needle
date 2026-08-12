import importlib.util
import math
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "backfill_ndcg", Path(__file__).parents[1] / "scripts" / "backfill_ndcg.py"
)
assert SPEC and SPEC.loader
backfill_ndcg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backfill_ndcg)
report_ndcg = backfill_ndcg.report_ndcg


def _pq(query, urls_ratings, rbp=0.5):
    return {
        "query": query,
        "rbp": rbp,
        "penalized_ratings": [r for _, r in urls_ratings],
        "results": [{"url": u, "rating": r} for u, r in urls_ratings],
        "search_error": None,
    }


def test_report_ndcg_uses_stored_ultimate_as_ideal():
    report = {
        "num_results": 5,
        "k": 5,
        "engines": {
            "a": {"per_query": [_pq("q", [("https://x.com/1", 0), ("https://y.com/1", 4)])]},
            "ultimate": {"per_query": [_pq("q", [("https://y.com/1", 4), ("https://x.com/1", 0)])]},
        },
    }
    out = report_ndcg(report)
    assert out["ultimate"] == pytest.approx(1.0)
    assert out["a"] == pytest.approx(1.0 / math.log2(3))


def test_report_ndcg_reconstructs_pool_when_ultimate_missing():
    report = {
        "num_results": 5,
        "k": 5,
        "engines": {
            "a": {"per_query": [_pq("q", [("https://y.com/1", 4)])]},
            "b": {"per_query": [_pq("q", [("https://x.com/1", 0), ("https://y.com/1", 4)])]},
        },
    }
    out = report_ndcg(report)
    assert out["a"] == pytest.approx(1.0)
    assert out["b"] == pytest.approx(1.0 / math.log2(3))


def test_report_ndcg_reconstruction_takes_best_rating_per_url():
    report = {
        "num_results": 5,
        "k": 5,
        "engines": {
            "a": {"per_query": [_pq("q", [("https://y.com/1", 2)])]},
            "b": {"per_query": [_pq("q", [("http://www.y.com/1/", 4)])]},
        },
    }
    out = report_ndcg(report)
    assert out["b"] == pytest.approx(1.0)
    assert out["a"] == pytest.approx(0.117)


def test_report_ndcg_excludes_zero_ideal_queries():
    report = {
        "num_results": 5,
        "k": 5,
        "engines": {
            "a": {
                "per_query": [
                    _pq("dead", [("https://x.com/1", 0)]),
                    _pq("live", [("https://y.com/1", 4)]),
                ]
            },
        },
    }
    out = report_ndcg(report)
    assert out["a"] == pytest.approx(1.0)


def test_report_ndcg_skips_unscored_and_errored_queries():
    errored = {
        "query": "q_err",
        "rbp": None,
        "penalized_ratings": [],
        "results": [],
        "search_error": {"error_type": "http_error"},
    }
    report = {
        "num_results": 5,
        "k": 5,
        "engines": {
            "a": {"per_query": [_pq("q", [("https://y.com/1", 4)]), errored]},
        },
    }
    assert report_ndcg(report)["a"] == pytest.approx(1.0)


def test_report_ndcg_supplies_ultimate_when_absent_from_report():
    report = {
        "num_results": 5,
        "k": 5,
        "engines": {"a": {"per_query": [_pq("q", [("https://y.com/1", 4)])]}},
    }
    assert report_ndcg(report)["ultimate"] == pytest.approx(1.0)
    dead = {
        "num_results": 5,
        "k": 5,
        "engines": {"a": {"per_query": [_pq("q", [("https://y.com/1", 0)])]}},
    }
    assert report_ndcg(dead)["ultimate"] == 0.0


def test_report_ndcg_passes_through_new_format():
    report = {"engines": {"a": {"mean_ndcg": 0.42}, "ultimate": {"mean_ndcg": 1.0}}}
    assert report_ndcg(report) == {"a": 0.42, "ultimate": 1.0}
