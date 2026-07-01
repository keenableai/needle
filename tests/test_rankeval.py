import pytest

from keenbench.rankeval import run_rbp
from keenbench.shared.search import SearchResult


class FakeEngine:
    engine = "fake"

    def __init__(self, results, error=None):
        self._results = results
        self._error = error

    async def search(self, query, *, num_results=10):
        if self._error is not None:
            return None, self._error
        return self._results[:num_results], None


class FakeJudge:
    async def complete(self, prompt, *, max_tokens, reasoning_effort):
        rating = 4 if "GOODDOC" in prompt else 0
        label = "FullyM" if rating == 4 else "FailsM"
        return f"rating: {rating}\nlabel: {label}\nreasoning: x", None


async def test_run_rbp_ranks_engines():
    good = [
        SearchResult(url="https://g1", title="GOODDOC one"),
        SearchResult(url="https://g2", title="GOODDOC two"),
    ]
    bad = [SearchResult(url="https://b1", title="nope")]
    report = await run_rbp(
        ["q1", "q2"],
        {"good": FakeEngine(good), "bad": FakeEngine(bad)},
        FakeJudge(),
        num_results=5,
        today="2026-07-01",
    )
    assert report["num_queries"] == 2
    g = report["engines"]["good"]["mean_rbp_at_5"]
    b = report["engines"]["bad"]["mean_rbp_at_5"]
    assert g > b
    assert g == pytest.approx((1 - 0.8) * (1.0 + 0.8 * 1.0))
    assert b == 0.0


async def test_run_rbp_excludes_search_errors_from_mean():
    good = [SearchResult(url="https://g1", title="GOODDOC one")]

    class FlakyEngine:
        engine = "flaky"

        async def search(self, query, *, num_results=10):
            if query == "q_err":
                return None, {"error_type": "http_error", "error_message": "503"}
            return good, None

    report = await run_rbp(
        ["q_ok", "q_err"], {"flaky": FlakyEngine()}, FakeJudge(), today="2026-07-01"
    )
    e = report["engines"]["flaky"]
    assert e["search_errors"] == 1
    assert e["num_scored"] == 1
    assert e["mean_rbp_at_5"] == pytest.approx((1 - 0.8) * 1.0)
    errored = next(pq for pq in e["per_query"] if pq["query"] == "q_err")
    assert errored["rbp"] is None
    assert errored["search_error"]["error_type"] == "http_error"


async def test_run_rbp_scores_empty_results_as_zero_not_error():
    report = await run_rbp(["q1"], {"empty": FakeEngine([])}, FakeJudge(), today="2026-07-01")
    e = report["engines"]["empty"]
    assert e["search_errors"] == 0
    assert e["num_scored"] == 1
    assert e["mean_rbp_at_5"] == 0.0


async def test_run_rbp_excludes_judge_errors_from_mean():
    results = [SearchResult(url="https://a", title="GOODDOC")]

    class FlakyJudge:
        async def complete(self, prompt, *, max_tokens, reasoning_effort):
            if "q_bad" in prompt:
                return None, {"error_type": "http_error", "error_message": "500"}
            return "rating: 4\nlabel: FullyM\nreasoning: x", None

    report = await run_rbp(
        ["q_good", "q_bad"], {"e": FakeEngine(results)}, FlakyJudge(), today="2026-07-01"
    )
    e = report["engines"]["e"]
    assert e["judge_errors"] == 1
    assert e["num_scored"] == 1
    assert e["mean_rbp_at_5"] == pytest.approx((1 - 0.8) * 1.0)
    bad = next(pq for pq in e["per_query"] if pq["query"] == "q_bad")
    assert bad["rbp"] is None
    assert bad["ratings"] == [None]
