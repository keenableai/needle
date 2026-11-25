import pytest

from needle.coding.models import doc_key
from needle.coding.score import GoldDoc, run_coding
from needle.shared.search import SearchResult


@pytest.mark.parametrize(
    ("url", "key"),
    [
        (
            "https://docs.python.org/3/library/itertools.html#itertools.groupby",
            "py:library/itertools",
        ),
        ("https://docs.python.org/3.12/library/itertools.html", "py:library/itertools"),
        ("https://docs.python.org/ja/3/library/itertools.html", "py:library/itertools"),
        (
            "https://numpy.org/doc/1.26/reference/generated/numpy.argsort.html",
            "numpy:reference/generated/numpy.argsort",
        ),
        (
            "https://numpy.org/devdocs/reference/generated/numpy.argsort.html",
            "numpy:reference/generated/numpy.argsort",
        ),
        (
            "https://pandas.pydata.org/pandas-docs/version/2.1.4/reference/api/pandas.DataFrame.explode.html",
            "pandas:reference/api/pandas.dataframe.explode",
        ),
        (
            "https://pandas.pydata.org/docs/dev/reference/api/pandas.DataFrame.explode.html",
            "pandas:reference/api/pandas.dataframe.explode",
        ),
        (
            "https://developer.mozilla.org/en-US/docs/Web/API/AbortSignal/timeout_static",
            "mdn:web/api/abortsignal/timeout_static",
        ),
        (
            "https://developer.mozilla.org/docs/Web/API/AbortSignal/timeout_static/",
            "mdn:web/api/abortsignal/timeout_static",
        ),
        (
            "https://github.com/Pandas-Dev/pandas/issues/63250#issuecomment-1",
            "gh:pandas-dev/pandas#63250",
        ),
        ("https://github.com/pandas-dev/pandas/pull/63250/files", "gh:pandas-dev/pandas#63250"),
        ("https://stackoverflow.com/questions/80003283/how-to-x", "so:80003283"),
        ("https://www.stackoverflow.com/q/80003283", "so:80003283"),
        ("https://stackoverflow.com/a/80003283", None),
        ("https://github.com/pandas-dev/pandas/blob/main/x.py", None),
        ("https://example.com/questions/80003283", None),
        ("http://[broken", None),
    ],
)
def test_doc_key(url, key):
    assert doc_key(url) == key


class FakeEngine:
    def __init__(self, results, error=None):
        self._results = results
        self._error = error
        self.latencies_ms = [10.0]
        self.reconnects = 0

    async def search(self, query, *, num_results=10):
        if self._error is not None:
            return None, self._error
        return self._results, None

    async def aclose(self):
        pass


GOLD = [
    GoldDoc(
        text="python group consecutive items",
        doc_key="py:library/itertools",
        bucket="api",
        syntax="plain",
    ),
    GoldDoc(
        text="pandas truediv bool",
        doc_key="gh:pandas-dev/pandas#63250",
        bucket="issue",
        syntax="site",
    ),
]


async def test_run_coding_matches_canonical_urls_only():
    docs = SearchResult(
        url="https://docs.python.org/3.13/library/itertools.html", title="", snippet=""
    )
    mirror = SearchResult(
        url="https://example.com/pandas-dev/pandas/issues/63250", title="", snippet=""
    )
    issue = SearchResult(
        url="https://github.com/pandas-dev/pandas/issues/63250", title="", snippet=""
    )
    report = await run_coding(
        GOLD,
        {"good": FakeEngine([mirror, docs, issue]), "bad": FakeEngine([mirror])},
    )
    good = report["engines"]["good"]
    assert good["recall_at_k"] == 1.0
    assert [pq["hit_rank"] for pq in good["per_query"]] == [2, 3]
    assert good["per_query"][0]["results"][1]["ids"] == {"doc": ["py:library/itertools"]}
    assert good["per_query"][0]["results"][0]["ids"] == {}
    assert good["by_bucket"]["issue"] == {"n": 1, "recall_at_k": 1.0}
    assert good["by_syntax"]["site"]["n"] == 1
    bad = report["engines"]["bad"]
    assert bad["recall_at_k"] == 0.0
    assert bad["misses_system_specific"] == 2
    assert report["engines"]["ultimate"]["recall_at_k"] == 1.0


async def test_run_coding_counts_engine_errors_as_misses():
    report = await run_coding(GOLD[:1], {"err": FakeEngine([], error={"error_type": "http"})})
    err = report["engines"]["err"]
    assert (err["num_scored"], err["search_errors"], err["recall_at_k"]) == (1, 1, 0.0)
