import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from keenbench.shared.ci import (
    ci_payload,
    per_query_score,
    query_id,
    score_row,
    updated_scores,
)

SPEC = importlib.util.spec_from_file_location(
    "publish_bench", Path(__file__).parents[1] / "scripts" / "publish_bench.py"
)
assert SPEC and SPEC.loader
publish_bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publish_bench)


def test_per_query_score_ndcg():
    assert per_query_score("news", {"ndcg": 0.61804, "search_error": None}) == 0.618
    assert per_query_score("news", {"ndcg": None, "search_error": None}) is None


def test_per_query_score_known_item():
    assert per_query_score("scholar", {"search_error": None, "hit_rank": 3}) == 1.0
    assert per_query_score("scholar", {"search_error": None, "hit_rank": None}) == 0.0
    assert per_query_score("scholar", {"search_error": {"error_type": "x"}, "hit_rank": 1}) is None


def test_per_query_score_finance_judge_error_backstop():
    pq = {"search_error": None, "hit_rank": None, "judge_errors": 2}
    assert per_query_score("finance", pq) is None
    assert per_query_score("finance", {**pq, "hit_rank": 2}) == 1.0
    assert per_query_score("finance", {**pq, "judge_errors": 0}) == 0.0


def _report(engine_scores, queries):
    return {
        "engines": {
            name: {
                "per_query": [
                    {"query": q, "ndcg": s, "search_error": None}
                    for q, s in zip(queries, scores, strict=True)
                ]
            }
            for name, scores in engine_scores.items()
        }
    }


def test_score_row_aligns_engines_on_shared_qids():
    row = score_row(_report({"a": [1.0, 0.5], "b": [0.0, None]}, ["q1", "q2"]), "news", "t")
    assert row["qids"] == [query_id("q1"), query_id("q2")]
    assert row["engines"] == {"a": [1.0, 0.5], "b": [0.0, None]}


def _rows(runs, bench="news"):
    return [
        score_row(_report(engine_scores, queries), bench, ts) for ts, queries, engine_scores in runs
    ]


def test_point_matches_query_weighted_mean():
    rows = _rows(
        [
            ("2026-08-16T00:00Z", ["a", "b"], {"e": [1.0, 0.0]}),
            ("2026-08-17T00:00Z", ["a", "c"], {"e": [1.0, 1.0]}),
        ]
    )
    out = ci_payload(rows, "2026-08-17T00:00Z", resamples=200)
    assert out["benches"]["news"]["engines"]["e"]["point"] == pytest.approx(0.75)


def _width(payload, engine="e"):
    c = payload["benches"]["news"]["engines"][engine]
    return c["hi"] - c["lo"]


def test_repeated_gold_set_does_not_shrink_interval():
    queries = [f"q{i}" for i in range(60)]
    scores = [1.0 if i < 40 else 0.0 for i in range(60)]
    one = _rows([("2026-08-17T00:00Z", queries, {"e": scores})])
    seven = _rows([(f"2026-08-{10 + d}T00:00Z", queries, {"e": scores}) for d in range(7)])
    w1 = _width(ci_payload(one, "2026-08-17T00:00Z", resamples=4000))
    w7 = _width(ci_payload(seven, "2026-08-17T00:00Z", resamples=4000))
    assert w7 == pytest.approx(w1, abs=0.02)


def test_fresh_queries_shrink_interval():
    scores = [1.0 if i < 40 else 0.0 for i in range(60)]
    one = _rows([("2026-08-17T00:00Z", [f"q0_{i}" for i in range(60)], {"e": scores})])
    seven = _rows(
        [
            (f"2026-08-{10 + d}T00:00Z", [f"q{d}_{i}" for i in range(60)], {"e": scores})
            for d in range(7)
        ]
    )
    w1 = _width(ci_payload(one, "2026-08-17T00:00Z", resamples=4000))
    w7 = _width(ci_payload(seven, "2026-08-17T00:00Z", resamples=4000))
    assert w7 < 0.6 * w1


def test_run_shock_widens_interval():
    runs = [
        (f"2026-08-{10 + d}T00:00Z", [f"q{d}_{i}" for i in range(40)], {"e": [0.2 + 0.1 * d] * 40})
        for d in range(7)
    ]
    payload = ci_payload(_rows(runs), "2026-08-17T00:00Z", resamples=4000)
    c = payload["benches"]["news"]["engines"]["e"]
    assert c["hi"] - c["lo"] > 0.1


def test_coverage_close_to_nominal():
    rng = np.random.default_rng(0)
    covered = 0
    sims = 200
    for i in range(sims):
        scores = rng.binomial(1, 0.6, size=200).astype(float).tolist()
        rows = _rows([("2026-08-17T00:00Z", [f"s{i}_q{j}" for j in range(200)], {"e": scores})])
        c = ci_payload(rows, "2026-08-17T00:00Z", resamples=1000)
        c = c["benches"]["news"]["engines"]["e"]
        covered += c["lo"] <= 0.6 <= c["hi"]
    assert covered / sims >= 0.88


def test_single_query_single_run_omitted():
    rows = _rows([("2026-08-17T00:00Z", ["only"], {"e": [1.0]})])
    out = ci_payload(rows, "2026-08-17T00:00Z", resamples=200)
    assert out["benches"] == {}


def test_deterministic_given_window_end():
    rows = _rows(
        [
            (
                "2026-08-17T00:00Z",
                [f"q{i}" for i in range(30)],
                {"e": [float(i % 2) for i in range(30)]},
            )
        ]
    )
    a = ci_payload(rows, "2026-08-17T00:00Z", resamples=500)
    b = ci_payload(rows, "2026-08-17T00:00Z", resamples=500)
    assert a == b


def test_updated_scores_prunes_and_republishes():
    old = {"ts": "2026-08-01T00:00Z", "bench": "news", "qids": [], "engines": {}}
    recent = {"ts": "2026-08-16T00:00Z", "bench": "news", "qids": [], "engines": {}}
    stale = {"ts": "2026-08-17T00:00Z", "bench": "news", "qids": ["x"], "engines": {}}
    fresh = {"ts": "2026-08-17T00:00Z", "bench": "news", "qids": ["y"], "engines": {}}
    out = updated_scores([old, recent, stale], [fresh], "2026-08-17T00:00Z")
    assert out == [recent, fresh]


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
                    {"query": "q1", "ndcg": 1.0, "search_error": None, "results": []},
                    {"query": "q2", "ndcg": 0.0, "search_error": None, "results": []},
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
    assert ci["benches"]["news"]["engines"]["e"]["point"] == pytest.approx(0.5)
