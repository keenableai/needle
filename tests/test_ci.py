import numpy as np
import pytest

from keenbench.shared.ci import ci_payload, score_row, updated_scores
from keenbench.shared.identity import query_hash
from keenbench.shared.rankeval import _summarize
from keenbench.shared.recall import recall_summary


def test_rankeval_summary_annotates_score():
    pqs = [
        {"ndcg": 0.5, "search_error": None, "judge_errors": 0},
        {"ndcg": None, "search_error": None, "judge_errors": 1},
    ]
    _summarize(pqs, latencies_ms=[])
    assert [pq["score"] for pq in pqs] == [0.5, None]


def test_recall_summary_annotates_score():
    pqs = [
        {"hit_rank": 1, "search_error": None},
        {"hit_rank": None, "search_error": None},
        {"hit_rank": None, "search_error": {"error_type": "x"}},
    ]
    recall_summary(pqs, pqs[:2], None)
    assert [pq["score"] for pq in pqs] == [1.0, 0.0, None]


def _report(engine_scores, queries):
    return {
        "engines": {
            name: {
                "per_query": [
                    {"query": q, "score": s} for q, s in zip(queries, scores, strict=True)
                ]
            }
            for name, scores in engine_scores.items()
        }
    }


def test_score_row_aligns_engines_on_shared_qids():
    row = score_row(_report({"a": [1.0, 0.61804], "b": [0.0, None]}, ["q1", "q2"]), "news", "t")
    assert row["qids"] == [query_hash("q1"), query_hash("q2")]
    assert row["engines"] == {"a": [1.0, 0.618], "b": [0.0, None]}


def _rows(runs):
    return [
        score_row(_report(engine_scores, queries), "news", ts)
        for ts, queries, engine_scores in runs
    ]


def test_point_matches_query_weighted_mean():
    rows = _rows(
        [
            ("2026-08-16T00:00Z", ["a", "b"], {"e": [1.0, 0.0]}),
            ("2026-08-17T00:00Z", ["a", "c"], {"e": [1.0, 1.0]}),
        ]
    )
    out = ci_payload(rows, "2026-08-17T00:00Z", resamples=200)
    assert out["benches"]["news"]["e"]["point"] == pytest.approx(0.75)
    assert out["runs"]["news"] == ["2026-08-16T00:00Z", "2026-08-17T00:00Z"]
    assert ci_payload(rows, "2026-08-17T00:00Z", resamples=200) == out


def _widths(query_name):
    scores = [1.0 if i < 40 else 0.0 for i in range(60)]

    def width(runs):
        payload = ci_payload(_rows(runs), "2026-08-17T00:00Z", resamples=4000)
        c = payload["benches"]["news"]["e"]
        return c["hi"] - c["lo"]

    one = width([("2026-08-17T00:00Z", [query_name(0, i) for i in range(60)], {"e": scores})])
    seven = width(
        [
            (f"2026-08-{10 + d}T00:00Z", [query_name(d, i) for i in range(60)], {"e": scores})
            for d in range(7)
        ]
    )
    return one, seven


def test_repeated_gold_set_does_not_shrink_interval():
    w1, w7 = _widths(lambda d, i: f"q{i}")
    assert w7 == pytest.approx(w1, abs=0.02)


def test_fresh_queries_shrink_interval():
    w1, w7 = _widths(lambda d, i: f"q{d}_{i}")
    assert w7 < 0.6 * w1


def test_run_shock_widens_interval():
    runs = [
        (f"2026-08-{10 + d}T00:00Z", [f"q{d}_{i}" for i in range(40)], {"e": [0.2 + 0.1 * d] * 40})
        for d in range(7)
    ]
    payload = ci_payload(_rows(runs), "2026-08-17T00:00Z", resamples=4000)
    c = payload["benches"]["news"]["e"]
    assert c["hi"] - c["lo"] > 0.1


def test_coverage_close_to_nominal():
    rng = np.random.default_rng(0)
    covered = 0
    sims = 200
    for i in range(sims):
        scores = rng.binomial(1, 0.6, size=200).astype(float).tolist()
        rows = _rows([("2026-08-17T00:00Z", [f"s{i}_q{j}" for j in range(200)], {"e": scores})])
        c = ci_payload(rows, "2026-08-17T00:00Z", resamples=1000)["benches"]["news"]["e"]
        covered += c["lo"] <= 0.6 <= c["hi"]
    assert covered / sims >= 0.88


def test_single_query_single_run_omitted():
    rows = _rows([("2026-08-17T00:00Z", ["only"], {"e": [1.0]})])
    out = ci_payload(rows, "2026-08-17T00:00Z", resamples=200)
    assert out["benches"] == {}


def test_updated_scores_prunes_and_republishes():
    old = {"ts": "2026-08-01T00:00Z", "bench": "news", "qids": [], "engines": {}}
    recent = {"ts": "2026-08-16T00:00Z", "bench": "news", "qids": [], "engines": {}}
    stale = {"ts": "2026-08-17T00:00Z", "bench": "news", "qids": ["x"], "engines": {}}
    fresh = {"ts": "2026-08-17T00:00Z", "bench": "news", "qids": ["y"], "engines": {}}
    assert updated_scores([old, recent, stale], [fresh], "2026-08-17T00:00Z") == [recent, fresh]
