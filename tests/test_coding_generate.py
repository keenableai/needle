import json
from datetime import UTC, datetime

from needle.coding.generate import run_generate
from needle.coding.models import Doc
from needle.coding.projection import query_ok, syntax_query
from needle.shared.io import serialize_row

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
HOUR = NOW.replace(minute=0)

API = Doc(
    "api",
    "py:library/itertools",
    "https://docs.python.org/3/library/itertools.html",
    "itertools.groupby",
    "groupby(iterable)\nMake an iterator that returns consecutive keys and groups.",
    context="python",
    banned=("itertools", "groupby"),
)
ISSUE = Doc(
    "issue",
    "gh:pandas-dev/pandas#63250",
    "https://github.com/pandas-dev/pandas/issues/63250",
    "BUG: Series bool truediv",
    "TypeError: operator 'truediv' not implemented for bool dtypes",
    context="pandas-dev/pandas",
    banned=("63250",),
)
QA = Doc(
    "qa",
    "so:80003283",
    "https://stackoverflow.com/questions/80003283/x",
    "How to compute a gradient column-wise in a pandas DataFrame",
    "np.gradient raises ValueError ambiguous truth value",
    context="python",
    banned=("80003283",),
)


def test_api_query_rejects_banned_names_in_any_form():
    assert query_ok("python iterator of consecutive equal key runs", API)
    assert not query_ok("python groupby consecutive equal key runs", API)
    assert not query_ok("python itertools consecutive equal key runs", API)
    camel = Doc("api", "k", "u", "Array.flatMap", "t", context="javascript", banned=("flatMap",))
    assert not query_ok("javascript array flat map then flatten one level", camel)
    assert not query_ok("python groups", API)


def test_issue_query_needs_one_verbatim_span():
    assert query_ok("pandas \"operator 'truediv' not implemented\" bool series", ISSUE)
    assert not query_ok('pandas "truediv is not supported" bool series', ISSUE)
    assert not query_ok("pandas operator truediv not implemented bool series", ISSUE)
    assert not query_ok("pandas \"operator 'truediv' not implemented\" 63250 bool", ISSUE)


def test_qa_query_must_rephrase_the_title():
    assert query_ok("pandas np.gradient ValueError ambiguous per column", QA)
    assert not query_ok("compute a gradient column-wise in a pandas DataFrame", QA)


def test_syntax_variants():
    query = "pandas \"operator 'truediv' not implemented\" bool"
    assert syntax_query(query, ISSUE, "quoted") == query
    assert syntax_query(query, ISSUE, "plain") == "pandas operator 'truediv' not implemented bool"
    assert syntax_query(query, ISSUE, "site").endswith(" bool site:github.com")
    assert syntax_query("python x y z", API, "site") == "python x y z site:docs.python.org"


class FakeApi:
    async def docs(self, *, n, seed):
        return [API][:n]


class FakeWindowed:
    def __init__(self, docs):
        self._docs = docs
        self.calls = []

    async def fetch(self, key, *, created_after, created_before):
        self.calls.append((key, created_after, created_before))
        return list(self._docs)

    issues = fetch
    questions = fetch


class FakeLLM:
    def __init__(self, replies):
        self._replies = replies

    async def complete(self, prompt, *, max_tokens, reasoning_effort):
        for marker, reply in self._replies.items():
            if marker in prompt:
                return reply, None
        return "NO_DISTINCT_QUERY", None


async def test_run_generate_builds_rows_per_type_and_counts_drops():
    github = FakeWindowed([ISSUE])
    stackexchange = FakeWindowed([QA])
    llm = FakeLLM(
        {
            "API reference page": "python iterator of consecutive equal key runs",
            "GitHub issue": "pandas \"operator 'truediv' not implemented\" bool series",
            "Stack Overflow": "compute a gradient column-wise in a pandas DataFrame",
        }
    )
    rows, stats = await run_generate(
        api=FakeApi(),
        github=github,
        stackexchange=stackexchange,
        llm=llm,
        hour_ts=HOUR,
        now=NOW,
        per_type=2,
        repos=("pandas-dev/pandas", "numpy/numpy"),
        tags=("python",),
        months_back=12,
        seed=0,
    )
    assert [r["query_origin"]["bucket"] for r in rows] == ["api", "issue"]
    assert rows[0]["gold"] == {
        "doc_key": "py:library/itertools",
        "ids": {"doc": "py:library/itertools"},
        "url": API.url,
        "title": API.title,
    }
    assert rows[1]["query_text"] == "pandas operator 'truediv' not implemented bool series"
    assert stats.candidates == {"api": 1, "issue": 1, "qa": 1}
    assert stats.rows == {"api": 1, "issue": 1, "qa": 0}
    assert stats.rejected == 1
    assert {key for key, _, _ in github.calls} == {"pandas-dev/pandas", "numpy/numpy"}
    assert all(after < before <= NOW.date() for _, after, before in github.calls)
    assert json.loads(serialize_row(rows[0])["gold"])["doc_key"] == "py:library/itertools"
