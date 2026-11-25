import zlib
from datetime import UTC, date, datetime

from needle.coding.sources import (
    GitHubClient,
    docs_bases,
    docsrs_entry,
    docsrs_items,
    host_label,
    load_mintlify_hosts,
    markdown_page,
    page_main_text,
    parse_feed,
    parse_inventory,
    parse_issue,
    parse_llms_txt,
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


def test_load_mintlify_hosts_skips_popular_hosts(tmp_path):
    path = tmp_path / "hosts.csv"
    path.write_text("docs.discord.com,1000000\ndocs.small.dev,50000000\nbad-line\n")
    assert load_mintlify_hosts(path, min_rank=5_000_000) == ["docs.small.dev"]
    assert len(load_mintlify_hosts()) > 1000


def test_host_label():
    assert host_label("docs.cognee.ai") == "cognee"
    assert host_label("developers.dwolla.com") == "dwolla"
    assert host_label("kingdee.mintlify.app") == "kingdee"


LLMS = (
    "# Cognee Documentation\n\n> Memory for agents.\n\n## Docs\n\n"
    + "\n".join(
        f"- [Page {i}](https://docs.cognee.ai/guides/page-{i}.md): about {i}" for i in range(10)
    )
    + "\n- [Home](https://docs.cognee.ai/)\n- [Elsewhere](https://example.com/x.md)\n"
)


def test_parse_llms_txt_cleans_name_and_keeps_same_host_pages():
    name, links = parse_llms_txt(LLMS, "docs.cognee.ai")
    assert name == "Cognee"
    assert links[0] == ("Page 0", "https://docs.cognee.ai/guides/page-0.md")
    assert len(links) == 10
    assert (
        parse_llms_txt(LLMS.replace("Cognee Documentation", "Mint Starter Kit"), "docs.cognee.ai")
        is None
    )
    assert parse_llms_txt(LLMS, "other.host") is None
    assert parse_llms_txt("<!doctype html>" + LLMS, "docs.cognee.ai") is None


def test_markdown_page_strips_frontmatter_and_needs_words():
    page = "---\ntitle: Billing\n---\n" + "Set an automatic reload threshold. " * 10
    assert markdown_page(page).startswith("Set an automatic reload threshold.")
    assert markdown_page("<!DOCTYPE html><html>" + "word " * 50) is None
    assert markdown_page("too short") is None


RSS = b"""<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item><title>Radar  AS types</title><link>https://developers.cloudflare.com/changelog/post/a/</link>
<pubDate>Wed, 19 Nov 2026 10:00:00 GMT</pubDate><description>short</description>
<content:encoded><![CDATA[<p>Radar now shows <b>AS categories</b>.</p>]]></content:encoded></item>
<item><title>No link</title><pubDate>Wed, 19 Nov 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM_FEED = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Drives SDK</title><link rel="alternate" href="https://vercel.com/changelog/drives"/>
<updated>2026-11-24T08:00:00Z</updated><summary type="html">&lt;p&gt;New SDKs.&lt;/p&gt;</summary></entry>
</feed>"""


def test_parse_feed_reads_rss_and_atom():
    (rss,) = parse_feed(RSS)
    assert (rss.title, rss.url, rss.text) == (
        "Radar AS types",
        "https://developers.cloudflare.com/changelog/post/a/",
        "Radar now shows AS categories .",
    )
    assert rss.published == datetime(2026, 11, 19, 10, tzinfo=UTC)
    (atom,) = parse_feed(ATOM_FEED)
    assert (atom.url, atom.text, atom.published) == (
        "https://vercel.com/changelog/drives",
        "New SDKs.",
        datetime(2026, 11, 24, 8, tzinfo=UTC),
    )
    assert parse_feed(b"not xml") == []


def test_page_main_text_prefers_main():
    assert page_main_text("<nav>menu</nav><main><p>Body text.</p></main>") == "Body text."
    assert page_main_text("<p>Only body.</p>") == "Only body."
