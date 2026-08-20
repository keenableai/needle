import pytest

from keenbench.scholar.ids import PaperIds
from keenbench.scholar.score import GoldPaper, ids_match, run_papers
from keenbench.shared.search import SearchResult


def _r(url, title="", snippet=""):
    return SearchResult(url=url, title=title, snippet=snippet)


class FakeEngine:
    def __init__(self, engine, table):
        self.engine = engine
        self.latencies_ms = []
        self._table = table

    async def search(self, query, *, num_results=10):
        entry = self._table.get(query)
        if isinstance(entry, dict) and entry.get("error"):
            return None, {"error_type": "http_error", "error_message": "boom"}
        return (entry or [])[:num_results], None

    async def aclose(self):
        pass


def test_ids_match():
    assert ids_match({"arxiv": "2506.12345"}, PaperIds(arxiv="2506.12345"))
    assert ids_match({"doi": "10.1/x", "pmid": "9"}, PaperIds(pmid="9"))
    assert not ids_match({"arxiv": "2506.12345"}, PaperIds(arxiv="2506.99999"))
    assert not ids_match({"doi": "10.1/x"}, PaperIds())


def _gold(text, bucket, ids, paper_key):
    return GoldPaper(text=text, paper_key=paper_key, ids=ids, bucket=bucket)


async def test_recall_mrr_and_rank():
    queries = [
        _gold("q1", "title", {"arxiv": "2506.00001"}, "2506.00001"),
        _gold("q2", "title", {"arxiv": "2506.00002"}, "2506.00002"),
    ]
    engine = FakeEngine(
        "keenable",
        {
            "q1": [
                _r("https://other.com"),
                _r("https://arxiv.org/abs/2506.00001", snippet="a preprint"),
            ],
            "q2": [_r("https://nope.com")],
        },
    )
    engine.latencies_ms = [50.0]
    report = await run_papers(queries, {"keenable": engine}, num_results=5)
    e = report["engines"]["keenable"]
    first, second = e["per_query"][0]["results"]
    assert first["matched"] is False
    assert second["matched"] is True
    assert second["snippet"] == "a preprint"
    assert e["num_scored"] == 2
    assert e["recall_at_k"] == 0.5
    assert e["mrr_at_k"] == pytest.approx(0.25)
    assert e["by_bucket"]["title"]["recall_at_k"] == 0.5
    assert e["latency"] == {
        "n": 1,
        "mean_ms": 50.0,
        "p50_ms": 50.0,
        "p95_ms": 50.0,
        "samples_ms": [50.0],
    }


async def test_search_error_excluded():
    queries = [_gold("q1", "title", {"arxiv": "2506.00001"}, "2506.00001")]
    engine = FakeEngine("exa", {"q1": {"error": True}})
    report = await run_papers(queries, {"exa": engine}, num_results=5)
    e = report["engines"]["exa"]
    assert e["num_scored"] == 0
    assert e["search_errors"] == 1
    assert e["recall_at_k"] == 0.0


async def test_title_and_body_reported_separately():
    queries = [
        _gold("t1", "title", {"arxiv": "2506.00001"}, "2506.00001"),
        _gold("b1", "body", {"arxiv": "2506.00001"}, "2506.00001"),
        _gold("t2", "title", {"arxiv": "2506.00002"}, "2506.00002"),
        _gold("b2", "body", {"arxiv": "2506.00002"}, "2506.00002"),
    ]
    engine = FakeEngine(
        "keenable",
        {
            "t1": [_r("https://arxiv.org/abs/2506.00001")],
            "b1": [_r("https://nope.com")],
            "t2": [_r("https://arxiv.org/abs/2506.00002")],
            "b2": [_r("https://arxiv.org/abs/2506.00002")],
        },
    )
    report = await run_papers(queries, {"keenable": engine}, num_results=5)
    bb = report["engines"]["keenable"]["by_bucket"]
    assert bb["title"]["recall_at_k"] == 1.0
    assert bb["body"]["recall_at_k"] == 0.5
    assert "shallow_index" not in report["engines"]["keenable"]


async def test_misses_classification():
    queries = [_gold("q1", "title", {"arxiv": "2506.00001"}, "2506.00001")]
    good = FakeEngine("good", {"q1": [_r("https://arxiv.org/abs/2506.00001")]})
    bad = FakeEngine("bad", {"q1": [_r("https://wrong.com")]})
    report = await run_papers(queries, {"good": good, "bad": bad}, num_results=5)
    assert report["engines"]["bad"]["misses_system_specific"] == 1
    assert report["engines"]["bad"]["misses_universal"] == 0

    only_bad = FakeEngine("bad", {"q1": [_r("https://wrong.com")]})
    report2 = await run_papers(queries, {"bad": only_bad}, num_results=5)
    assert report2["engines"]["bad"]["misses_universal"] == 1
    assert report2["engines"]["bad"]["misses_system_specific"] == 0


class FakeIdConv:
    def __init__(self, mapping):
        self._mapping = mapping
        self.calls = 0

    async def pmc_to_pmid(self, pmcids):
        self.calls += 1
        return {p: self._mapping.get(p) for p in pmcids}


async def test_pmc_resolution_enables_hit():
    queries = [_gold("q1", "title", {"pmid": "999"}, "999")]
    engine = FakeEngine(
        "keenable",
        {"q1": [_r("https://pmc.ncbi.nlm.nih.gov/articles/PMC7654321")]},
    )
    idconv = FakeIdConv({"7654321": "999"})
    report = await run_papers(queries, {"keenable": engine}, num_results=5, idconv=idconv)
    assert idconv.calls == 1
    assert report["engines"]["keenable"]["recall_at_k"] == 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-q"])


async def test_ultimate_pools_hits_across_engines():
    queries = [
        _gold("q1", "title", {"arxiv": "2506.00001"}, "2506.00001"),
        _gold("q2", "title", {"arxiv": "2506.00002"}, "2506.00002"),
    ]
    a = FakeEngine(
        "a",
        {
            "q1": [_r("https://other.com"), _r("https://arxiv.org/abs/2506.00001")],
            "q2": [_r("https://nope.com")],
        },
    )
    b = FakeEngine("b", {"q1": [_r("https://nope.com")], "q2": {"error": True}})
    report = await run_papers(queries, {"a": a, "b": b}, num_results=5)
    ult = report["engines"]["ultimate"]
    assert ult["recall_at_k"] == 0.5
    assert ult["mrr_at_k"] is None
    assert ult["num_scored"] == 2
    assert ult["latency"] is None
    assert ult["misses_system_specific"] == 0
    assert ult["misses_universal"] == 1
    pq1 = ult["per_query"][0]
    assert pq1["hit_rank"] == 1
    assert pq1["results"][0]["url"] == "https://arxiv.org/abs/2506.00001"
    assert pq1["n_results"] == 3


async def test_ultimate_unscored_when_all_engines_fail():
    queries = [_gold("q1", "title", {"arxiv": "2506.00001"}, "2506.00001")]
    report = await run_papers(queries, {"e": FakeEngine("e", {"q1": {"error": True}})})
    ult = report["engines"]["ultimate"]
    assert ult["num_scored"] == 0
    assert ult["search_errors"] == 1


async def test_no_engines_no_ultimate():
    queries = [_gold("q1", "title", {"arxiv": "2506.00001"}, "2506.00001")]
    report = await run_papers(queries, {}, num_results=5)
    assert report["engines"] == {}
