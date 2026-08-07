import importlib.util
import json
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "daily_queries", Path(__file__).parents[1] / "scripts" / "daily_queries.py"
)
assert SPEC and SPEC.loader
daily_queries = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(daily_queries)


def test_benches_include_agentic_rare():
    assert ("agentic_rare", "agentic_rare.jsonl", "agentic_rare.json") in daily_queries.BENCHES


def test_bench_rows_keep_full_records():
    report = {"engines": {"keenable": {"per_query": [{"query": "rare one"}]}}}
    queries_text = "\n".join(
        json.dumps(r)
        for r in (
            {"query_text": "rare one", "query_hash": "a" * 16, "query_source": "agentic_rare"},
            {"query_text": "not evaluated", "query_hash": "b" * 16},
        )
    )
    rows = daily_queries._bench_rows("2026-08-06T0732Z", "agentic_rare", queries_text, report)
    assert rows == [
        {
            "query_text": "rare one",
            "query_hash": "a" * 16,
            "query_source": "agentic_rare",
            "run_id": "2026-08-06T0732Z",
            "bench": "agentic_rare",
        }
    ]


def test_rare_rows_fallback_shape():
    report = {"engines": {"keenable": {"per_query": [{"query": "rare one"}]}}}
    assert daily_queries._rare_rows("2026-08-06T0732Z", report) == [
        {"run_id": "2026-08-06T0732Z", "bench": "agentic_rare", "query_text": "rare one"}
    ]
