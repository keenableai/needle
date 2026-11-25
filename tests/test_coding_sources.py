import zlib
from datetime import date

from needle.coding.sources import (
    GitHubClient,
    docs_bases,
    docsrs_entry,
    docsrs_items,
    parse_inventory,
    parse_issue,
    parse_question,
    small_repo_names,
    sphinx_entry,
)


def _inventory(lines: list[str]) -> bytes:
    header = b"# Sphinx inventory version 2\n# Project: x\n# Version: 1\n# z\n"
    return header + zlib.compress("\n".join(lines).encode())


def test_parse_inventory_keeps_public_dotted_python_objects():
    raw = _inventory(
        [
            "itertools.groupby py:function 1 library/itertools.html#$ -",
            "csv.csvreader.__next__ py:method 1 library/csv.html#$ -",
            "itertools py:module 0 library/itertools.html#module-$ -",
            "glossary std:label -1 glossary.html#$ Glossary",
            "Toplevel py:class 1 api.html#$ -",
        ]
    )
    assert parse_inventory(raw) == [
        ("itertools.groupby", "library/itertools.html#itertools.groupby")
    ]
    assert parse_inventory(b"not an inventory") == []
    assert parse_inventory(b"# Sphinx inventory\nb\nc\nd\nnot zlib") == []


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


def test_docs_bases_prefers_listed_docs_then_read_the_docs():
    info = {
        "project_urls": {
            "Documentation": "https://webargs.readthedocs.io/en/latest",
            "Source": "https://github.com/marshmallow-code/webargs",
        }
    }
    assert docs_bases(info, "webargs") == ["https://webargs.readthedocs.io/en/latest/"]
    assert docs_bases({}, "cf_units") == ["https://cf-units.readthedocs.io/en/latest/"]


DOCSRS_ALL = """
<ul class="all-items">
<li><a href="struct.Endpoint.html">Endpoint</a></li>
<li><a href="config/struct.Config.html">config::Config</a></li>
<li><a href="fn.connect.html">connect</a></li>
<li><a href="index.html">crate</a></li>
<li><a href="struct.Endpoint.html">Endpoint</a></li>
</ul>
"""

DOCSRS_ITEM = """
<pre class="rust item-decl"><code>pub struct <a href="#">WireMsg</a>(pub UsrMsgBytes);</code></pre>
<details class="toggle top-doc" open><summary class="hideme"><span>Expand</span></summary>
<div class="docblock"><p>Final type serialised and sent on the wire by the endpoint to its peers.</p>
<div class="example-wrap"><pre>let x = 1;</pre></div></div></details>
<h2 id="fields">Tuple Fields</h2>
"""


def test_docsrs_items_and_entry():
    assert docsrs_items(DOCSRS_ALL) == [
        "struct.Endpoint.html",
        "config/struct.Config.html",
        "fn.connect.html",
    ]
    assert docsrs_entry(DOCSRS_ITEM) == (
        "pub struct WireMsg (pub UsrMsgBytes);\n"
        "Final type serialised and sent on the wire by the endpoint to its peers."
    )
    short = DOCSRS_ITEM.replace(
        "Final type serialised and sent on the wire by the endpoint to its peers.", "A message."
    )
    assert docsrs_entry(short) is None
    assert docsrs_entry("<p>no declaration</p>") is None


def test_small_repo_names_keeps_repos_with_open_issues():
    payload = {
        "items": [
            {"full_name": "a/one", "has_issues": True, "open_issues_count": 40},
            {"full_name": "b/two", "has_issues": True, "open_issues_count": 3},
            {"full_name": "c/three", "has_issues": False, "open_issues_count": 90},
        ]
    }
    assert small_repo_names(payload) == ["a/one"]
    assert small_repo_names(None) == []


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
