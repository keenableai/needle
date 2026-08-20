import math

import pytest

from keenbench.shared.rankeval import EvalQuery, run_ndcg
from keenbench.shared.search import SearchResult

TODAY = "2026-07-01"
PROFILE_YAML = (
    "query_type: specific\nquery_domain: other\nquery_search_operators_exist: no\n"
    "query_main_aspects: the fact\nquery_aux_aspects: ''\n"
    "query_content_archetype: evergreen"
)


def q(text):
    return EvalQuery(text=text, today=TODAY)


def is_profile_prompt(prompt):
    return "Classify a web search query" in prompt


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

    async def complete(self, prompt, *, max_tokens, reasoning_effort, system=None):
        self.calls += 1
        full = f"{system}\n\n{prompt}" if system else prompt
        self.prompts.append(full)
        if is_profile_prompt(full):
            return PROFILE_YAML, None
        rating = 4 if "GOODDOC" in full else 0
        label = "FullyM" if rating == 4 else "FailsM"
        return f"rating: {rating}\nlabel: {label}\nreasoning: x", None


async def test_run_ndcg_ranks_engines():
    good = [
        SearchResult(url="https://g1", title="GOODDOC one"),
        SearchResult(url="https://g2", title="GOODDOC two"),
    ]
    bad = [SearchResult(url="https://b1", title="nope")]
    report = await run_ndcg(
        [q("q1"), q("q2")],
        {"good": FakeEngine(good), "bad": FakeEngine(bad)},
        FakeJudge(),
        num_results=5,
    )
    assert report["num_queries"] == 2
    g = report["engines"]["good"]["mean_ndcg"]
    b = report["engines"]["bad"]["mean_ndcg"]
    assert g > b
    assert g == pytest.approx(1.0)
    assert b == 0.0


async def test_run_ndcg_excludes_search_errors_from_mean():
    good = [SearchResult(url="https://g1", title="GOODDOC one")]

    class FlakyEngine:
        engine = "flaky"
        latencies_ms = []

        async def search(self, query, *, num_results=10):
            if query == "q_err":
                return None, {"error_type": "http_error", "error_message": "503"}
            return good, None

    report = await run_ndcg([q("q_ok"), q("q_err")], {"flaky": FlakyEngine()}, FakeJudge())
    e = report["engines"]["flaky"]
    assert e["search_errors"] == 1
    assert e["num_scored"] == 1
    assert e["mean_ndcg"] == pytest.approx(1.0)
    errored = next(pq for pq in e["per_query"] if pq["query"] == "q_err")
    assert errored["ndcg"] is None
    assert errored["search_error"]["error_type"] == "http_error"


async def test_run_ndcg_excludes_queries_with_empty_pool():
    report = await run_ndcg([q("q1")], {"empty": FakeEngine([])}, FakeJudge())
    e = report["engines"]["empty"]
    assert e["search_errors"] == 0
    assert e["num_scored"] == 0
    assert e["mean_ndcg"] == 0.0
    assert e["per_query"][0]["ndcg"] is None


async def test_run_ndcg_excludes_queries_with_no_relevant_pool():
    report = await run_ndcg(
        [q("q1")],
        {"e": FakeEngine([SearchResult(url="https://a.com/1", title="nope")])},
        FakeJudge(),
    )
    assert report["engines"]["e"]["num_scored"] == 0
    assert report["engines"]["e"]["per_query"][0]["ndcg"] is None
    assert report["engines"]["ultimate"]["num_scored"] == 0


async def test_run_ndcg_scores_ordering_against_pooled_ideal():
    results = [
        SearchResult(url="https://bad.com/1", title="nope"),
        SearchResult(url="https://good.com/1", title="GOODDOC"),
    ]
    report = await run_ndcg([q("q1")], {"e": FakeEngine(results)}, FakeJudge())
    pq = report["engines"]["e"]["per_query"][0]
    assert pq["ndcg"] == pytest.approx(1.0 / math.log2(3))


async def test_run_ndcg_excludes_judge_errors_from_mean():
    results = [SearchResult(url="https://a", title="GOODDOC")]

    class FlakyJudge:
        async def complete(self, prompt, *, max_tokens, reasoning_effort, system=None):
            if "q_bad" in prompt:
                return None, {"error_type": "http_error", "error_message": "500"}
            return "rating: 4\nlabel: FullyM\nreasoning: x", None

    report = await run_ndcg([q("q_good"), q("q_bad")], {"e": FakeEngine(results)}, FlakyJudge())
    e = report["engines"]["e"]
    assert e["judge_errors"] == 1
    assert e["num_scored"] == 1
    assert e["mean_ndcg"] == pytest.approx(1.0)
    bad = next(pq for pq in e["per_query"] if pq["query"] == "q_bad")
    assert bad["ndcg"] is None
    assert bad["ratings"] == [None]


async def test_run_ndcg_judges_each_engine_on_its_own_snippet():
    lean = SearchResult(url="https://shared", title="nope", snippet="short")
    richer = SearchResult(url="https://shared", title=None, snippet="GOODDOC but much longer")
    judge = FakeJudge()
    report = await run_ndcg(
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


async def test_run_ndcg_judges_identical_docs_once_across_engines():
    doc = SearchResult(url="https://shared", title="GOODDOC", snippet="same")
    judge = FakeJudge()
    report = await run_ndcg([q("q1")], {"a": FakeEngine([doc]), "b": FakeEngine([doc])}, judge)
    assert report["judged_pairs"] == 1
    assert judge.calls == 2
    assert report["engines"]["a"]["per_query"][0]["ratings"] == [4]
    assert report["engines"]["b"]["per_query"][0]["ratings"] == [4]


async def test_run_ndcg_penalizes_duplicate_urls():
    results = [
        SearchResult(url="https://ex.com/1", title="GOODDOC"),
        SearchResult(url="https://www.ex.com/1/", title="GOODDOC"),
        SearchResult(url="https://ex.com/2", title="GOODDOC"),
    ]
    report = await run_ndcg([q("q1")], {"e": FakeEngine(results)}, FakeJudge())
    pq = report["engines"]["e"]["per_query"][0]
    assert pq["ratings"] == [4, 4, 4]
    assert pq["penalized_ratings"] == [4, 0, 4]
    expected = 1.0 + 1.0 / math.log2(4)
    assert pq["dcg"] == pytest.approx(expected)
    ideal = 1.0 + 1.0 / math.log2(3)
    assert pq["ndcg"] == pytest.approx(expected / ideal)


async def test_run_ndcg_same_domain_results_not_penalized():
    results = [
        SearchResult(url="https://ex.com/1", title="GOODDOC"),
        SearchResult(url="https://ex.com/2", title="GOODDOC"),
        SearchResult(url="https://ex.com/3", title="GOODDOC"),
    ]
    report = await run_ndcg([q("q1")], {"e": FakeEngine(results)}, FakeJudge())
    pq = report["engines"]["e"]["per_query"][0]
    assert pq["penalized_ratings"] == [4, 4, 4]
    assert pq["ndcg"] == pytest.approx(1.0)


async def test_run_ndcg_reports_latency():
    timed = FakeEngine([])
    timed.latencies_ms = [100.0, 300.0]

    report = await run_ndcg([q("q1")], {"timed": timed, "plain": FakeEngine([])}, FakeJudge())
    assert report["engines"]["timed"]["latency"] == {
        "n": 2,
        "mean_ms": 200.0,
        "p50_ms": 100.0,
        "p95_ms": 300.0,
        "samples_ms": [100.0, 300.0],
    }
    assert report["engines"]["plain"]["latency"] is None


async def test_run_ndcg_uses_per_query_today():
    judge = FakeJudge()
    queries = [
        EvalQuery(text="GOODDOC q1", today="2026-01-01"),
        EvalQuery(text="GOODDOC q2", today="2026-02-02"),
    ]
    await run_ndcg(queries, {"e": FakeEngine([SearchResult(url="https://a")])}, judge)
    assert any("Today's date: 2026-01-01" in p for p in judge.prompts)
    assert any("Today's date: 2026-02-02" in p for p in judge.prompts)


async def test_run_ndcg_ultimate_pools_engines():
    a = FakeEngine([SearchResult(url="https://one.com/a", title="GOODDOC a")])
    b = FakeEngine([SearchResult(url="https://two.com/b", title="GOODDOC b")])
    report = await run_ndcg([q("q1")], {"a": a, "b": b}, FakeJudge())
    ult = report["engines"]["ultimate"]
    assert ult["mean_ndcg"] == pytest.approx(1.0)
    a_ndcg = report["engines"]["a"]["mean_ndcg"]
    assert a_ndcg == pytest.approx(1.0 / (1.0 + 1.0 / math.log2(3)))
    assert ult["mean_ndcg"] > a_ndcg
    assert ult["latency"] is None
    pq = ult["per_query"][0]
    assert pq["n_results"] == 2
    assert {r["url"] for r in pq["results"]} == {"https://one.com/a", "https://two.com/b"}


async def test_run_ndcg_ultimate_dedupes_shared_urls():
    doc = SearchResult(url="https://one.com/a", title="GOODDOC")
    report = await run_ndcg(
        [q("q1")], {"a": FakeEngine([doc]), "b": FakeEngine([doc])}, FakeJudge()
    )
    pq = report["engines"]["ultimate"]["per_query"][0]
    assert pq["n_results"] == 1
    assert pq["ndcg"] == pytest.approx(1.0)


async def test_run_ndcg_ultimate_dedupes_url_variants():
    a = FakeEngine([SearchResult(url="https://one.com/a", title="GOODDOC", snippet="short")])
    b = FakeEngine(
        [SearchResult(url="http://www.one.com/a/", title="GOODDOC", snippet="GOODDOC longer")]
    )
    judge = FakeJudge()
    report = await run_ndcg([q("q1")], {"a": a, "b": b}, judge)
    assert report["judged_pairs"] == 2
    assert judge.calls == 3
    pq = report["engines"]["ultimate"]["per_query"][0]
    assert pq["n_results"] == 1
    assert pq["ndcg"] == pytest.approx(1.0)
    assert report["engines"]["a"]["per_query"][0]["ratings"] == [4]
    assert report["engines"]["b"]["per_query"][0]["ratings"] == [4]


async def test_run_ndcg_ultimate_takes_best_rating_per_url():
    a = FakeEngine([SearchResult(url="https://one.com/a", title="nope", snippet="meh")])
    b = FakeEngine([SearchResult(url="http://www.one.com/a/", title="GOODDOC", snippet="rich")])
    report = await run_ndcg([q("q1")], {"a": a, "b": b}, FakeJudge())
    assert report["engines"]["a"]["per_query"][0]["ratings"] == [0]
    assert report["engines"]["b"]["per_query"][0]["ratings"] == [4]
    pq = report["engines"]["ultimate"]["per_query"][0]
    assert pq["n_results"] == 1
    assert pq["ratings"] == [4]
    assert pq["ndcg"] == pytest.approx(1.0)


async def test_run_ndcg_ultimate_unscored_when_all_engines_fail():
    err = {"error_type": "http_error", "error_message": "503"}
    report = await run_ndcg([q("q1")], {"a": FakeEngine([], error=err)}, FakeJudge())
    ult = report["engines"]["ultimate"]
    assert ult["search_errors"] == 1
    assert ult["num_scored"] == 0
    assert ult["per_query"][0]["search_error"]["error_type"] == "all_engines_failed"


async def test_run_ndcg_ultimate_discards_failed_pooled_judgements():
    class FlakyJudge:
        async def complete(self, prompt, *, max_tokens, reasoning_effort, system=None):
            if "badhost" in prompt:
                return None, {"error_type": "http_error", "error_message": "500"}
            return "rating: 4\nlabel: FullyM\nreasoning: x", None

    a = FakeEngine([SearchResult(url="https://goodhost/a", title="fine")])
    b = FakeEngine([SearchResult(url="https://badhost/b", title="broken")])
    report = await run_ndcg([q("q1")], {"a": a, "b": b}, FlakyJudge())
    assert report["engines"]["a"]["num_scored"] == 1
    ult = report["engines"]["ultimate"]
    assert ult["num_scored"] == 1
    assert ult["judge_errors"] == 0
    assert ult["per_query"][0]["n_results"] == 1
    assert ult["per_query"][0]["results"][0]["url"] == "https://goodhost/a"


async def test_run_ndcg_no_engines_no_ultimate():
    report = await run_ndcg([q("q1")], {}, FakeJudge())
    assert report["engines"] == {}


async def test_run_ndcg_shares_query_profile_across_pairs():
    results = [
        SearchResult(url="https://ex.com/1", title="GOODDOC"),
        SearchResult(url="https://other.com/2", title="GOODDOC"),
    ]
    judge = FakeJudge()
    report = await run_ndcg([q("q1")], {"e": FakeEngine(results)}, judge)
    profile_prompts = [p for p in judge.prompts if is_profile_prompt(p)]
    judge_prompts = [p for p in judge.prompts if not is_profile_prompt(p)]
    assert len(profile_prompts) == 1
    assert len(judge_prompts) == 2
    assert all("- Query type: specific" in p for p in judge_prompts)
    assert all("- the fact" in p for p in judge_prompts)
    pq = report["engines"]["e"]["per_query"][0]
    assert pq["query_profile"] == {
        "query_type": "specific",
        "query_domain": "other",
        "query_search_operators_exist": False,
        "query_main_aspects": ("the fact",),
        "query_aux_aspects": (),
        "query_content_archetype": "evergreen",
    }
    assert report["engines"]["ultimate"]["per_query"][0]["query_profile"] == pq["query_profile"]


async def test_run_ndcg_judges_without_profile_when_classification_fails():
    class NoProfileJudge:
        async def complete(self, prompt, *, max_tokens, reasoning_effort, system=None):
            if is_profile_prompt(f"{system}\n\n{prompt}" if system else prompt):
                return None, {"error_type": "http_error", "error_message": "500"}
            return "rating: 4\nlabel: FullyM\nreasoning: x", None

    results = [SearchResult(url="https://a", title="GOODDOC")]
    report = await run_ndcg([q("q1")], {"e": FakeEngine(results)}, NoProfileJudge())
    pq = report["engines"]["e"]["per_query"][0]
    assert pq["query_profile"] is None
    assert pq["ratings"] == [4]
    assert pq["judge_errors"] == 0
