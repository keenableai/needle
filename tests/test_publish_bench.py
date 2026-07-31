import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "publish_bench", Path(__file__).parents[1] / "scripts" / "publish_bench.py"
)
assert SPEC and SPEC.loader
publish_bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publish_bench)
finance_rows = publish_bench.finance_rows
scholar_rows = publish_bench.scholar_rows


def _report(by_bucket):
    return {
        "num_queries": 8,
        "engines": {
            "engine": {
                "recall_at_k": 0.5,
                "mrr_at_k": 0.4,
                "by_bucket": by_bucket,
                "by_syntax": {},
                "num_scored": 7,
                "search_errors": 1,
                "latency": None,
            }
        },
    }


def test_scholar_rows_publish_slice_denominators():
    row = scholar_rows(
        _report(
            {
                "title": {"n": 2, "recall_at_k": 0.5},
                "body": {"n": 5, "recall_at_k": 0.6},
            }
        ),
        "2026-01-01T00:00:00Z",
    )[0]
    assert row["title_n"] == 2
    assert row["body_n"] == 5


def test_suite_rows_publish_slice_denominators():
    row = finance_rows(
        _report(
            {
                "filings": {"n": 3, "recall_at_k": 1 / 3},
                "filingdoc": {"n": 4, "recall_at_k": 0.75},
            }
        ),
        "2026-01-01T00:00:00Z",
    )[0]
    assert row["filings_n"] == 3
    assert row["filingdoc_n"] == 4
