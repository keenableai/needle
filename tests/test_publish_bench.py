import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest

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


def test_publish_writes_ci_files(tmp_path):
    report = {
        "num_queries": 2,
        "engines": {
            "e": {
                "mean_ndcg": 0.5,
                "num_scored": 2,
                "search_errors": 0,
                "judge_errors": 0,
                "latency": None,
                "per_query": [
                    {"query": "q1", "score": 1.0, "search_error": None, "results": []},
                    {"query": "q2", "score": 0.0, "search_error": None, "results": []},
                ],
            }
        },
    }
    ndcg = tmp_path / "ndcg.json"
    ndcg.write_text(json.dumps(report), encoding="utf-8")
    site = tmp_path / "site"
    publish_bench.publish(
        site=str(site), runs_out=str(tmp_path / "runs"), ndcg=str(ndcg), ts="2026-08-17T00:00Z"
    )
    scores = (site / "data" / "ci_scores.jsonl").read_text(encoding="utf-8")
    assert json.loads(scores)["engines"]["e"] == [1.0, 0.0]
    ci = json.loads((site / "data" / "ci.json").read_text(encoding="utf-8"))
    assert ci["window_end"] == "2026-08-17T00:00Z"
    assert ci["benches"]["news"]["e"]["point"] == pytest.approx(0.5)


def test_publish_auto_ts_skips_taken_minute(tmp_path, monkeypatch, capsys):
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    (site / "data" / "runs.json").write_text(
        json.dumps([{"id": "2026-08-17T0000Z", "ts": "2026-08-17T00:00Z", "artifacts": []}]),
        encoding="utf-8",
    )

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 8, 17, 0, 0, tzinfo=tz)

    monkeypatch.setattr(publish_bench, "datetime", FrozenDatetime)
    publish_bench.publish(site=str(site), runs_out=str(tmp_path / "runs"))
    assert capsys.readouterr().out.strip() == "2026-08-17T00:01Z"
    ids = [r["id"] for r in json.loads((site / "data" / "runs.json").read_text(encoding="utf-8"))]
    assert ids == ["2026-08-17T0000Z", "2026-08-17T0001Z"]
