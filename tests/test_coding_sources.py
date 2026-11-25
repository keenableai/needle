import zlib
from datetime import date

from needle.coding.sources import (
    GitHubClient,
    mdn_names,
    parse_inventory,
    parse_issue,
    parse_question,
    sphinx_entry,
)


def _inventory(lines: list[str]) -> bytes:
    header = b"# Sphinx inventory version 2\n# Project: x\n# Version: 1\n# z\n"
    return header + zlib.compress("\n".join(lines).encode())


def test_parse_inventory_keeps_public_python_objects_under_prefix():
    raw = _inventory(
        [
            "itertools.groupby py:function 1 library/itertools.html#$ -",
            "csv.csvreader.__next__ py:method 1 library/csv.html#$ -",
            "itertools py:module 0 library/itertools.html#module-$ -",
            "glossary std:label -1 glossary.html#$ Glossary",
            "tutorial.func py:function 1 tutorial/x.html#$ -",
        ]
    )
    assert parse_inventory(raw, path_prefix="library/") == [
        ("itertools.groupby", "library/itertools.html#itertools.groupby")
    ]
    assert parse_inventory(b"not an inventory", path_prefix="library/") == []
    assert parse_inventory(b"a\nb\nc\nd\nnot zlib", path_prefix="library/") == []


PAGE = """
<dl class="py function">
<dt class="sig sig-object py" id="itertools.groupby">
<span class="sig-prename">itertools.</span><span class="sig-name">groupby</span>(<em>iterable</em>)
<a class="headerlink" href="#itertools.groupby" title="Link">¶</a></dt>
<dd><p>Make an iterator that returns consecutive keys and groups from the
<em>iterable</em>.</p>
<p>The key is a function computing a key value for each element.</p>
</dd></dl>
<dl><dt id="itertools.short">short()</dt><dd><p>Too short.</p></dd></dl>
"""


def test_sphinx_entry_reads_signature_and_description():
    entry = sphinx_entry(PAGE, "itertools.groupby")
    assert entry == (
        "itertools. groupby ( iterable )\n"
        "Make an iterator that returns consecutive keys and groups from the iterable . "
        "The key is a function computing a key value for each element."
    )
    assert sphinx_entry(PAGE, "itertools.short") is None
    assert sphinx_entry(PAGE, "itertools.missing") is None


def test_mdn_names():
    assert mdn_names("/en-US/docs/Web/API/AbortSignal/timeout_static") == (
        "AbortSignal",
        "timeout",
    )
    assert mdn_names("/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array/flatMap") == (
        "Array",
        "flatMap",
    )
    assert mdn_names("/en-US/docs/Web/JavaScript/Reference/Errors/Not_defined") is None
    assert mdn_names("/en-US/docs/Web/JavaScript/Reference/Operators") is None
    assert mdn_names("/en-US/docs/Web/CSS/color") is None


def test_parse_issue_skips_pull_requests_and_strips_template_comments():
    item = {
        "html_url": "https://github.com/pandas-dev/pandas/issues/63250",
        "number": 63250,
        "title": "BUG:  truediv  fails",
        "body": "<!-- template -->\nTypeError: operator 'truediv' not implemented",
    }
    doc = parse_issue(item, "pandas-dev/pandas")
    assert doc is not None
    assert (doc.key, doc.title, doc.context, doc.banned) == (
        "gh:pandas-dev/pandas#63250",
        "BUG: truediv fails",
        "pandas-dev/pandas",
        ("63250",),
    )
    assert doc.text == "TypeError: operator 'truediv' not implemented"
    assert parse_issue({**item, "pull_request": {"url": "x"}}, "pandas-dev/pandas") is None
    assert parse_issue({**item, "body": "<!-- only -->"}, "pandas-dev/pandas") is None


def test_parse_question_requires_score_and_answer():
    item = {
        "link": "https://stackoverflow.com/questions/80003283/how-to-x",
        "question_id": 80003283,
        "title": "Why &quot;x&quot; fails",
        "body": "<p>I call <code>np.gradient</code> &amp; get an error.</p>",
        "score": 2,
        "answer_count": 1,
    }
    doc = parse_question(item, "python")
    assert doc is not None
    assert (doc.key, doc.title, doc.text, doc.banned) == (
        "so:80003283",
        'Why "x" fails',
        "I call np.gradient & get an error.",
        ("80003283",),
    )
    assert parse_question({**item, "score": 0}, "python") is None
    assert parse_question({**item, "answer_count": 0}, "python") is None


async def test_source_clients_record_fetch_errors():
    client = GitHubClient()

    async def fail(method, url, **kwargs):
        return None, {"error_type": "http_error", "error_message": "403: rate limit"}

    client._request_json = fail
    docs = await client.issues(
        "pandas-dev/pandas", created_after=date(2026, 1, 1), created_before=date(2026, 2, 1)
    )
    assert docs == []
    assert client.errors == ["github pandas-dev/pandas: http_error: 403: rate limit"]
