import dataclasses
import json
from datetime import UTC, datetime

import pytest

from needle.coding.cli import Coding, parse_counts
from needle.coding.generate import GenStats, run_generate
from needle.coding.models import Doc, build_row
from needle.coding.projection import query_ok, syntax_query
from needle.shared.io import serialize_row

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
HOUR = NOW.replace(minute=0)

API = Doc(
    "api",
    "https://docs.python.org/3/library/itertools.html",
    "itertools.groupby",
    "groupby(iterable)\nMake an iterator that returns consecutive keys and groups.",
    context="python",
    banned=("itertools", "groupby"),
)
ISSUE = Doc(
    "issue",
    "https://github.com/pandas-dev/pandas/issues/63250",
    "BUG: Series bool truediv",
    "TypeError: operator 'truediv' not implemented for bool dtypes",
    context="pandas-dev/pandas",
    banned=("63250",),
)
QA = Doc(
    "qa",
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
    camel = Doc("api", "u", "Array.flatMap", "t", context="javascript", banned=("flatMap",))
    assert not query_ok("javascript array flat map then flatten one level", camel)
    assert not query_ok("python groups", API)
    assert not query_ok("iterator of consecutive equal key runs grouped", API)


def test_issue_query_needs_one_verbatim_span():
    assert query_ok("pandas \"operator 'truediv' not implemented\" bool series", ISSUE)
    assert not query_ok('pandas "truediv is not supported" bool series', ISSUE)
    assert not query_ok("pandas operator truediv not implemented bool series", ISSUE)
    assert not query_ok("pandas \"operator 'truediv' not implemented\" 63250 bool", ISSUE)
    assert not query_ok("\"operator 'truediv' not implemented\" bool series dtype", ISSUE)


def test_qa_query_must_rephrase_the_title():
    assert query_ok("pandas np.gradient ValueError ambiguous per column", QA)
    assert not query_ok("compute a gradient column-wise in a pandas DataFrame", QA)
    assert not query_ok("pandas gradient numerical derivative slope estimate", QA)
    assert not query_ok(
        "How to compute a gradient column-wise in a pandas DataFrame ValueError ambiguous", QA
    )
    with_tag = dataclasses.replace(QA, text=f"{QA.text} in python")
    assert not query_ok("python valueerror pandas gradient per column", with_tag)


def test_syntax_variants():
    query = "pandas \"operator 'truediv' not implemented\" bool"
    assert syntax_query(query, ISSUE, "quoted") == query
    assert syntax_query(query, ISSUE, "plain") == "pandas operator 'truediv' not implemented bool"
    assert syntax_query(query, ISSUE, "site").endswith(" bool site:github.com")
    assert syntax_query("python x y z", API, "site") == "python x y z site:docs.python.org"


class FakeApi:
    errors: list[str] = []

    async def docs(self, *, n, seed):
        return [API][:n]

    async def distinct(self, query, doc):
        return True


class FakeWindowed:
    def __init__(self, docs, errors=()):
        self._docs = docs
        self.calls = []
        self.errors = list(errors)

    async def fetch(self, key, *, created_after, created_before):
        self.calls.append((key, created_after, created_before))
        return list(self._docs)

    issues = fetch
    questions = fetch

    async def distinct(self, query, doc):
        return True

    async def small_repos(self, *, now, seed, n):
        return ["small/one", "small/two"][:n]


class FakeLLM:
    def __init__(self, replies):
        self._replies = replies

    async def complete(self, prompt, *, max_tokens, reasoning_effort):
        for marker, reply in self._replies.items():
            if marker in prompt:
                return reply, None
        return "NO_DISTINCT_QUERY", None


async def test_run_generate_builds_rows_per_type_and_counts_drops():
    github = FakeWindowed([ISSUE], errors=["github numpy/numpy: http_error: 403"])
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
        counts={"api": 2, "issue": 2, "qa": 1},
        repos=("pandas-dev/pandas", "numpy/numpy"),
        tags=("python",),
        months_back=12,
        seed=0,
    )
    assert [r["query_origin"]["bucket"] for r in rows] == ["api", "issue"]
    assert rows[0]["gold"] == {
        "doc_key": "doc:docs.python.org/library/itertools",
        "ids": {"doc": "doc:docs.python.org/library/itertools"},
        "url": API.url,
        "title": API.title,
    }
    assert rows[1]["query_text"] == "pandas operator 'truediv' not implemented bool series"
    assert stats.candidates == {"api": 1, "issue": 1, "qa": 1}
    assert stats.rejected == 1
    assert stats.source_errors == ["github numpy/numpy: http_error: 403"]
    assert {key for key, _, _ in github.calls} == {"pandas-dev/pandas", "numpy/numpy"}
    assert all(after < before <= NOW.date() for _, after, before in github.calls)
    assert json.loads(serialize_row(rows[0])["gold"])["doc_key"] == (
        "doc:docs.python.org/library/itertools"
    )
    assert len({(after, before) for _, after, before in github.calls}) == 1


async def test_run_generate_samples_small_repos_without_a_repo_list():
    github = FakeWindowed([ISSUE])
    rows, _ = await run_generate(
        api=None,
        github=github,
        stackexchange=None,
        llm=FakeLLM({"GitHub issue": "pandas \"operator 'truediv' not implemented\" bool"}),
        hour_ts=HOUR,
        now=NOW,
        counts={"issue": 1},
        repos=(),
        tags=(),
        months_back=12,
        seed=0,
    )
    assert [r["query_origin"]["bucket"] for r in rows] == ["issue"]
    assert {key for key, _, _ in github.calls} == {"small/one", "small/two"}


def test_generate_refuses_a_set_missing_a_doc_type(tmp_path, monkeypatch):
    class DummyLLM:
        async def aclose(self):
            pass

    async def fake_run_generate(**kwargs):
        row = build_row(API, query_text="q", syntax="plain", hour_ts=HOUR)
        return [row], GenStats(candidates={"api": 1, "issue": 3})

    monkeypatch.setattr("needle.coding.cli.require_openrouter_client", lambda *a, **k: DummyLLM())
    monkeypatch.setattr("needle.coding.cli.run_generate", fake_run_generate)
    out = tmp_path / "coding.jsonl"
    with pytest.raises(SystemExit, match="no issue queries"):
        Coding().generate(out=str(out), counts="api=1,issue=1")
    assert not out.exists()


def test_parse_counts():
    assert parse_counts("api=20,issue=20,qa=10") == {"api": 20, "issue": 20, "qa": 10}
    assert parse_counts("mintlify=20,fresh=10") == {"mintlify": 20, "fresh": 10}
    for bad in ("api=0", "api=x", "docs=5", ""):
        with pytest.raises(SystemExit):
            parse_counts(bad)


MINT = Doc(
    "mintlify",
    "https://docs.lithosai.com/billing",
    "Billing",
    "Set an automatic reload threshold and a monthly cap for credits.",
    context="LithosAI",
)
FRESH = Doc(
    "fresh",
    "https://vercel.com/changelog/drives",
    "Vercel Drives adds CLI commands",
    "Drives REST API now supports drive-specific permissions and standalone SDKs.",
    context="Vercel",
)


def test_mintlify_and_fresh_queries_need_product_and_new_words():
    assert query_ok("LithosAI automatic reload threshold monthly cap", MINT)
    assert not query_ok("automatic reload threshold monthly cap credits", MINT)
    assert not query_ok("LithosAI billing", MINT)
    assert query_ok("Vercel drives drive-specific permissions standalone SDKs", FRESH)
    assert not query_ok("Vercel Drives adds CLI commands", FRESH)


class FakeSource:
    errors: list[str] = []

    def __init__(self, docs, unique=True):
        self._docs = docs
        self._unique = unique

    async def docs(self, *, n, seed, now=None):
        return list(self._docs)[:n]

    async def distinct(self, query, doc):
        return self._unique


async def test_run_generate_adds_mintlify_and_fresh_types():
    llm = FakeLLM(
        {
            "product's developer documentation": "LithosAI automatic reload threshold monthly cap",
            "changelog": "Vercel drives drive-specific permissions standalone SDKs",
        }
    )
    rows, stats = await run_generate(
        api=None,
        github=None,
        stackexchange=None,
        mintlify=FakeSource([MINT]),
        changelogs=FakeSource([FRESH], unique=False),
        llm=llm,
        hour_ts=HOUR,
        now=NOW,
        counts={"mintlify": 1, "fresh": 1},
        repos=(),
        tags=(),
        months_back=12,
        seed=0,
    )
    assert [r["query_origin"]["bucket"] for r in rows] == ["mintlify"]
    assert rows[0]["gold"]["doc_key"] == "doc:docs.lithosai.com/billing"
    assert stats.candidates == {"mintlify": 1, "fresh": 1}
    assert stats.not_distinct == 1
