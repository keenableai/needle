import pytest

from keenbench.shared.rankeval import EvalQuery, run_rbp
from keenbench.shared.search import SearchResult

TODAY = "2026-07-01"
PROFILE_YAML = (
    "objective: find it\ncore_aspects:\n  - the fact\n"
    "query_type: B\narchetype: Evergreen\ndated_event: false"
)


def q(text):
    return EvalQuery(text=text, today=TODAY)


def is_profile_prompt(prompt):
    return "query_type" in prompt


class FakeEngine:
    engine = "fake"

    def __init__(self, results, error=None):
        self._results = results
        self._error = error
        self.latencies_ms = []

    async def search(self, query, *, num_results=10):
        if self._error is not None:
            return None, self._error
        return self._results[:num_results], None


class FakeJudge:
    def __init__(self):
        self.calls = 0
        self.prompts = []

    async def complete(self, prompt, *, max_tokens, reasoning_effort):
        self.calls += 1
        self.prompts.append(prompt)
        if is_profile_prompt(prompt):
            return PROFILE_YAML, None
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
        [q("q1"), q("q2")],
        {"good": FakeEngine(good), "bad": FakeEngine(bad)},
        FakeJudge(),
        num_results=5,
    )
    assert report["num_queries"] == 2
    g = report["engines"]["good"]["mean_rbp"]
    b = report["engines"]["bad"]["mean_rbp"]
    assert g > b
    assert g == pytest.approx((1 - 0.8) * (1.0 + 0.8 * 1.0))
    assert b == 0.0


async def test_run_rbp_excludes_search_errors_from_mean():
    good = [SearchResult(url="https://g1", title="GOODDOC one")]

    class FlakyEngine:
        engine = "flaky"
        latencies_ms = []

        async def search(self, query, *, num_results=10):
            if query == "q_err":
                return None, {"error_type": "http_error", "error_message": "503"}
            return good, None

    report = await run_rbp([q("q_ok"), q("q_err")], {"flaky": FlakyEngine()}, FakeJudge())
    e = report["engines"]["flaky"]
    assert e["search_errors"] == 1
    assert e["num_scored"] == 1
    assert e["mean_rbp"] == pytest.approx((1 - 0.8) * 1.0)
    errored = next(pq for pq in e["per_query"] if pq["query"] == "q_err")
    assert errored["rbp"] is None
    assert errored["search_error"]["error_type"] == "http_error"


async def test_run_rbp_scores_empty_results_as_zero_not_error():
    report = await run_rbp([q("q1")], {"empty": FakeEngine([])}, FakeJudge())
    e = report["engines"]["empty"]
    assert e["search_errors"] == 0
    assert e["num_scored"] == 1
    assert e["mean_rbp"] == 0.0


async def test_run_rbp_excludes_judge_errors_from_mean():
    results = [SearchResult(url="https://a", title="GOODDOC")]

    class FlakyJudge:
        async def complete(self, prompt, *, max_tokens, reasoning_effort):
            if "q_bad" in prompt:
                return None, {"error_type": "http_error", "error_message": "500"}
            return "rating: 4\nlabel: FullyM\nreasoning: x", None

    report = await run_rbp([q("q_good"), q("q_bad")], {"e": FakeEngine(results)}, FlakyJudge())
    e = report["engines"]["e"]
    assert e["judge_errors"] == 1
    assert e["num_scored"] == 1
    assert e["mean_rbp"] == pytest.approx((1 - 0.8) * 1.0)
    bad = next(pq for pq in e["per_query"] if pq["query"] == "q_bad")
    assert bad["rbp"] is None
    assert bad["ratings"] == [None]


async def test_run_rbp_judges_each_engine_on_its_own_snippet():
    lean = SearchResult(url="https://shared", title="nope", snippet="short")
    richer = SearchResult(url="https://shared", title=None, snippet="GOODDOC but much longer")
    judge = FakeJudge()
    report = await run_rbp(
        [q("q1")],
        {"a": FakeEngine([lean]), "b": FakeEngine([richer])},
        judge,
    )
    assert report["judged_pairs"] == 2
    assert judge.calls == 3
    assert is_profile_prompt(judge.prompts[0])
    assert "short" in judge.prompts[1]
    assert "GOODDOC but much longer" not in judge.prompts[1]
    assert "GOODDOC but much longer" in judge.prompts[2]
    assert report["engines"]["a"]["per_query"][0]["ratings"] == [0]
    assert report["engines"]["b"]["per_query"][0]["ratings"] == [4]


async def test_run_rbp_judges_identical_docs_once_across_engines():
    doc = SearchResult(url="https://shared", title="GOODDOC", snippet="same")
    judge = FakeJudge()
    report = await run_rbp([q("q1")], {"a": FakeEngine([doc]), "b": FakeEngine([doc])}, judge)
    assert report["judged_pairs"] == 1
    assert judge.calls == 2
    assert report["engines"]["a"]["per_query"][0]["ratings"] == [4]
    assert report["engines"]["b"]["per_query"][0]["ratings"] == [4]


async def test_run_rbp_applies_domain_redundancy_penalties():
    results = [
        SearchResult(url="https://ex.com/1", title="GOODDOC"),
        SearchResult(url="https://ex.com/2", title="GOODDOC"),
        SearchResult(url="https://ex.com/3", title="GOODDOC"),
    ]
    report = await run_rbp([q("q1")], {"e": FakeEngine(results)}, FakeJudge())
    pq = report["engines"]["e"]["per_query"][0]
    assert pq["ratings"] == [4, 4, 4]
    assert pq["penalized_ratings"] == [4, 3, 2]
    expected = (1 - 0.8) * (1.0 + 0.8 * 0.667 + 0.8**2 * 0.117)
    assert pq["rbp"] == pytest.approx(expected)


async def test_run_rbp_reports_latency():
    timed = FakeEngine([])
    timed.latencies_ms = [100.0, 300.0]

    report = await run_rbp([q("q1")], {"timed": timed, "plain": FakeEngine([])}, FakeJudge())
    assert report["engines"]["timed"]["latency"] == {
        "n": 2,
        "mean_ms": 200.0,
        "p50_ms": 100.0,
        "p95_ms": 300.0,
        "samples_ms": [100.0, 300.0],
    }
    assert report["engines"]["plain"]["latency"] is None


async def test_run_rbp_uses_per_query_today():
    judge = FakeJudge()
    queries = [
        EvalQuery(text="GOODDOC q1", today="2026-01-01"),
        EvalQuery(text="GOODDOC q2", today="2026-02-02"),
    ]
    await run_rbp(queries, {"e": FakeEngine([SearchResult(url="https://a")])}, judge)
    assert any("Today's date: 2026-01-01" in p for p in judge.prompts)
    assert any("Today's date: 2026-02-02" in p for p in judge.prompts)


async def test_run_rbp_ultimate_pools_engines():
    a = FakeEngine([SearchResult(url="https://one.com/a", title="GOODDOC a")])
    b = FakeEngine([SearchResult(url="https://two.com/b", title="GOODDOC b")])
    report = await run_rbp([q("q1")], {"a": a, "b": b}, FakeJudge())
    ult = report["engines"]["ultimate"]
    assert ult["mean_rbp"] == pytest.approx((1 - 0.8) * (1.0 + 0.8))
    assert ult["mean_rbp"] > report["engines"]["a"]["mean_rbp"]
    assert ult["latency"] is None
    pq = ult["per_query"][0]
    assert pq["n_results"] == 2
    assert {r["url"] for r in pq["results"]} == {"https://one.com/a", "https://two.com/b"}


async def test_run_rbp_ultimate_dedupes_shared_urls():
    doc = SearchResult(url="https://one.com/a", title="GOODDOC")
    report = await run_rbp([q("q1")], {"a": FakeEngine([doc]), "b": FakeEngine([doc])}, FakeJudge())
    pq = report["engines"]["ultimate"]["per_query"][0]
    assert pq["n_results"] == 1
    assert pq["rbp"] == pytest.approx((1 - 0.8) * 1.0)


async def test_run_rbp_ultimate_dedupes_url_variants():
    a = FakeEngine([SearchResult(url="https://one.com/a", title="GOODDOC", snippet="short")])
    b = FakeEngine(
        [SearchResult(url="http://www.one.com/a/", title="GOODDOC", snippet="GOODDOC longer")]
    )
    judge = FakeJudge()
    report = await run_rbp([q("q1")], {"a": a, "b": b}, judge)
    assert report["judged_pairs"] == 2
    assert judge.calls == 3
    pq = report["engines"]["ultimate"]["per_query"][0]
    assert pq["n_results"] == 1
    assert pq["rbp"] == pytest.approx((1 - 0.8) * 1.0)
    assert report["engines"]["a"]["per_query"][0]["ratings"] == [4]
    assert report["engines"]["b"]["per_query"][0]["ratings"] == [4]


async def test_run_rbp_ultimate_takes_best_rating_per_url():
    a = FakeEngine([SearchResult(url="https://one.com/a", title="nope", snippet="meh")])
    b = FakeEngine([SearchResult(url="http://www.one.com/a/", title="GOODDOC", snippet="rich")])
    report = await run_rbp([q("q1")], {"a": a, "b": b}, FakeJudge())
    assert report["engines"]["a"]["per_query"][0]["ratings"] == [0]
    assert report["engines"]["b"]["per_query"][0]["ratings"] == [4]
    pq = report["engines"]["ultimate"]["per_query"][0]
    assert pq["n_results"] == 1
    assert pq["ratings"] == [4]
    assert pq["rbp"] == pytest.approx((1 - 0.8) * 1.0)


async def test_run_rbp_ultimate_unscored_when_all_engines_fail():
    err = {"error_type": "http_error", "error_message": "503"}
    report = await run_rbp([q("q1")], {"a": FakeEngine([], error=err)}, FakeJudge())
    ult = report["engines"]["ultimate"]
    assert ult["search_errors"] == 1
    assert ult["num_scored"] == 0
    assert ult["per_query"][0]["search_error"]["error_type"] == "all_engines_failed"


async def test_run_rbp_ultimate_discards_failed_pooled_judgements():
    class FlakyJudge:
        async def complete(self, prompt, *, max_tokens, reasoning_effort):
            if "badhost" in prompt:
                return None, {"error_type": "http_error", "error_message": "500"}
            return "rating: 4\nlabel: FullyM\nreasoning: x", None

    a = FakeEngine([SearchResult(url="https://goodhost/a", title="fine")])
    b = FakeEngine([SearchResult(url="https://badhost/b", title="broken")])
    report = await run_rbp([q("q1")], {"a": a, "b": b}, FlakyJudge())
    assert report["engines"]["a"]["num_scored"] == 1
    ult = report["engines"]["ultimate"]
    assert ult["num_scored"] == 1
    assert ult["judge_errors"] == 0
    assert ult["per_query"][0]["n_results"] == 1
    assert ult["per_query"][0]["results"][0]["url"] == "https://goodhost/a"


async def test_run_rbp_no_engines_no_ultimate():
    report = await run_rbp([q("q1")], {}, FakeJudge())
    assert report["engines"] == {}


async def test_run_rbp_shares_query_profile_across_pairs():
    results = [
        SearchResult(url="https://ex.com/1", title="GOODDOC"),
        SearchResult(url="https://other.com/2", title="GOODDOC"),
    ]
    judge = FakeJudge()
    report = await run_rbp([q("q1")], {"e": FakeEngine(results)}, judge)
    profile_prompts = [p for p in judge.prompts if is_profile_prompt(p)]
    judge_prompts = [p for p in judge.prompts if not is_profile_prompt(p)]
    assert len(profile_prompts) == 1
    assert len(judge_prompts) == 2
    assert all("- Query type: B" in p for p in judge_prompts)
    assert all("- the fact" in p for p in judge_prompts)
    pq = report["engines"]["e"]["per_query"][0]
    assert pq["query_profile"] == {
        "query_type": "B",
        "archetype": "Evergreen",
        "dated_event": False,
        "objective": "find it",
        "core_aspects": ("the fact",),
    }
    assert report["engines"]["ultimate"]["per_query"][0]["query_profile"] == pq["query_profile"]


async def test_run_rbp_judges_without_profile_when_classification_fails():
    class NoProfileJudge:
        async def complete(self, prompt, *, max_tokens, reasoning_effort):
            if is_profile_prompt(prompt):
                return None, {"error_type": "http_error", "error_message": "500"}
            return "rating: 4\nlabel: FullyM\nreasoning: x", None

    results = [SearchResult(url="https://a", title="GOODDOC")]
    report = await run_rbp([q("q1")], {"e": FakeEngine(results)}, NoProfileJudge())
    pq = report["engines"]["e"]["per_query"][0]
    assert pq["query_profile"] is None
    assert pq["ratings"] == [4]
    assert pq["judge_errors"] == 0
