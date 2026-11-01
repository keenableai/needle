import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("backfill_scores", SCRIPTS / "backfill_scores.py")
assert SPEC and SPEC.loader
backfill_scores = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backfill_scores)

SERVICE = {"error_type": "http_error", "error_message": "503: busy"}
ACCOUNT = {"error_type": "http_error", "error_message": "401: bad key"}


def _pq(query, field, *, hit_rank=None, det_rank=None, results=(), error=None):
    return {
        "query": query,
        "field": field,
        "value": None,
        "bucket": "filings",
        "syntax": "plain",
        "tier": "",
        "freshness_window": "static",
        "hit_rank": hit_rank,
        "det_rank": det_rank,
        "judged": 1 if hit_rank != det_rank else 0,
        "judge_errors": 0,
        "n_results": len(results),
        "results": [
            {"url": f"https://x.com/{i}", "title": "", "snippet": s} for i, s in enumerate(results)
        ],
        "search_error": error,
    }


def _gold(query, field, field_type, value):
    return {"query_text": query, "gold": {"field": field, "field_type": field_type, "value": value}}


def test_finance_backfill_drops_money_judge_hits_and_scores_service_failures():
    snippets = ("net income of about $500 million", "net income of $801 million")
    report = {
        "num_queries": 2,
        "num_results": 5,
        "engines": {
            "a": {
                "per_query": [
                    _pq("q1", "net_income", hit_rank=1, results=snippets),
                    _pq("q2", "ceo", hit_rank=1, results=("chief executive",)),
                ]
            },
            "b": {
                "per_query": [
                    _pq("q1", "net_income", error=SERVICE),
                    _pq("q2", "ceo", error=ACCOUNT),
                ]
            },
        },
    }
    gold = [_gold("q1", "net_income", "money", 801e6), _gold("q2", "ceo", "person", "Jane Roe")]

    backfill_scores.rematch_money(report, gold)
    engines = backfill_scores.rescore(report, "finance")["engines"]

    q1 = engines["a"]["per_query"][0]
    assert (q1["hit_rank"], q1["det_rank"], q1["judged"]) == (2, 2, 0)
    assert engines["a"]["per_query"][1]["hit_rank"] == 1
    assert engines["a"]["recall_at_k"] == pytest.approx(1.0)
    assert engines["a"]["mrr_at_k"] == pytest.approx(0.75)
    assert (engines["b"]["recall_at_k"], engines["b"]["num_scored"]) == (0.0, 1)
    assert (engines["b"]["account_errors"], engines["b"]["service_errors"]) == (1, 1)
    assert engines["ultimate"]["recall_at_k"] == pytest.approx(1.0)


def test_recall_backfill_keeps_hits_and_rescores_failures():
    def pq(hit_rank=None, error=None):
        return {
            "query": "q",
            "bucket": "title",
            "hit_rank": hit_rank,
            "n_results": 2,
            "results": [{"url": "https://x.com/a"}, {"url": "https://x.com/p"}]
            if error is None
            else [],
            "search_error": error,
        }

    report = {
        "num_results": 10,
        "engines": {
            "a": {"per_query": [pq(hit_rank=2)]},
            "b": {"per_query": [pq(error=SERVICE)]},
            "c": {"per_query": [pq(error=ACCOUNT)]},
        },
    }
    engines = backfill_scores.rescore(report, "scholar")["engines"]

    assert (engines["a"]["recall_at_k"], engines["a"]["mrr_at_k"]) == (1.0, 0.5)
    assert (engines["b"]["recall_at_k"], engines["b"]["num_scored"]) == (0.0, 1)
    assert engines["c"]["num_scored"] == 0
    assert engines["ultimate"]["recall_at_k"] == 1.0
