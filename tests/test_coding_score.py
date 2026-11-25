import pytest

from needle.coding.models import doc_key
from needle.coding.score import GoldDoc, run_coding
from needle.shared.search import SearchResult


@pytest.mark.parametrize(
    ("url", "key"),
    [
        (
            "https://python-flint.readthedocs.io/en/latest/fmpz.html#flint.fmpz.gcd",
            "doc:python-flint.readthedocs.io/fmpz",
        ),
        (
            "https://python-flint.readthedocs.io/en/v0.6.0/fmpz.html",
            "doc:python-flint.readthedocs.io/fmpz",
        ),
        (
            "https://docs.python.org/3.12/library/tkinter.html",
            "doc:docs.python.org/library/tkinter",
        ),
        (
            "https://docs.python.org/ja/3/library/tkinter.html",
            "doc:docs.python.org/library/tkinter",
        ),
        ("http://docs.python.org//library/tkinter.html", "doc:docs.python.org/library/tkinter"),
        ("https://webargs.readthedocs.io/en/stable/api/", "doc:webargs.readthedocs.io/api"),
        (
            "https://webargs.readthedocs.io/en/latest/api/index.html",
            "doc:webargs.readthedocs.io/api",
        ),
        (
            "https://doc.qt.io/qtforpython-6.11/PySide6/QtOpcUa/QOpcUaNode.html",
            "doc:doc.qt.io/qtforpython/pyside6/qtopcua/qopcuanode",
        ),
        (
            "https://doc.qt.io/qtforpython-6/PySide6/QtOpcUa/QOpcUaNode.html",
            "doc:doc.qt.io/qtforpython/pyside6/qtopcua/qopcuanode",
        ),
        ("https://example.com/docs/api/main.html", "doc:example.com/docs/api/main"),
        ("https://example.com/en/guide", "doc:example.com/en/guide"),
        (
            "https://docs.rs/tracing-tunnel/latest/tracing_tunnel/struct.TracingEventSender.html",
            "rustdoc:tracing_tunnel/struct.tracingeventsender",
        ),
        (
            "https://docs.rs/tracing-tunnel/0.1.0/tracing_tunnel/struct.TracingEventSender.html#method.new",
            "rustdoc:tracing_tunnel/struct.tracingeventsender",
        ),
        (
            "https://slowli.github.io/tracing-toolbox/tracing_tunnel/struct.TracingEventSender.html",
            "rustdoc:tracing_tunnel/struct.tracingeventsender",
        ),
        (
            "https://docs.rs/qp2p/latest/qp2p/config/struct.Config.html",
            "rustdoc:qp2p/config/struct.config",
        ),
        ("https://docs.rs/qp2p/latest/qp2p/", "doc:docs.rs/qp2p/qp2p"),
        ("https://docs.rs/qp2p/0.36.4/src/qp2p/lib.rs.html", "doc:docs.rs/qp2p/src/qp2p/lib.rs"),
        (
            "https://github.com/Pandas-Dev/pandas/issues/63250#issuecomment-1",
            "gh:pandas-dev/pandas#63250",
        ),
        ("https://github.com/pandas-dev/pandas/pull/63250/files", "gh:pandas-dev/pandas#63250"),
        (
            "https://github.com/pandas-dev/pandas/blob/main/x.py",
            "doc:github.com/pandas-dev/pandas/blob/x.py",
        ),
        ("https://stackoverflow.com/questions/80003283/how-to-x", "so:80003283"),
        ("https://www.stackoverflow.com/q/80003283", "so:80003283"),
        ("https://stackoverflow.com/a/80003283", "doc:stackoverflow.com/a/80003283"),
        ("http://[broken", None),
        ("not a url", None),
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
        doc_key="doc:docs.python.org/library/itertools",
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
    assert good["per_query"][0]["results"][1]["ids"] == {
        "doc": ["doc:docs.python.org/library/itertools"]
    }
    assert good["per_query"][0]["results"][0]["ids"] == {
        "doc": ["doc:example.com/pandas-dev/pandas/issues/63250"]
    }
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
