import json
from collections import Counter

from needle.coding.models import Doc
from needle.coding.siblings import llms_full_corpus, ranks_first, sphinx_corpus, terms
from needle.coding.sources import (
    ApiDocsClient,
    ChangelogClient,
    GitHubClient,
    MintlifyClient,
)


def test_terms_stem_words_and_split_identifiers():
    assert terms("HashMap returns sorted_keys") == Counter(
        {"hash": 1, "map": 1, "return": 1, "sort": 1, "key": 1}
    )


def test_ranks_first_needs_the_gold_strictly_ahead():
    corpus = {
        "gold": terms("reload threshold monthly cap credits billing"),
        "usage": terms("usage limits credits billing dashboard"),
        "same": terms("reload threshold monthly cap credits billing"),
    }
    assert ranks_first("reload threshold cap", {k: corpus[k] for k in ("gold", "usage")}, "gold")
    assert not ranks_first("usage dashboard credits", corpus, "gold")
    assert not ranks_first("reload threshold cap", corpus, "gold")
    assert not ranks_first("reload threshold cap", corpus, "missing")


SEARCHINDEX = (
    "Search.setIndex("
    + json.dumps(
        {
            "docnames": ["api", "guide/index"],
            "terms": {"reload": 0, "threshold": [0, 1], "cap": 1},
            "titleterms": {"api": 0},
        }
    )
    + ")"
)


def test_sphinx_corpus_reads_page_terms():
    corpus = sphinx_corpus(SEARCHINDEX, "https://claripy.rtfd.io/en/latest/")
    assert corpus == {
        "doc:claripy.rtfd.io/api": Counter({"reload": 1, "threshold": 1, "api": 1}),
        "doc:claripy.rtfd.io/guide": Counter({"threshold": 1, "cap": 1}),
    }
    old_format = 'Search.setIndex({filenames:["api"],terms:{"a,b:c":0,reload:0}})'
    assert sphinx_corpus(old_format, "https://x.io/") == {
        "doc:x.io/api": Counter({"a,b:c": 1, "reload": 1})
    }
    assert sphinx_corpus("Search.setIndex({docnames:[}", "https://x/") == {}


LLMS_FULL = (
    "# Billing\nSource: https://docs.lithosai.com/billing\n\nSet a reload threshold.\n\n"
    "## Caps\nMonthly cap.\n\n"
    "# Usage\nSource: https://docs.lithosai.com/usage.md\n\nUsage limits."
)


def test_llms_full_corpus_splits_pages_by_source():
    corpus = llms_full_corpus(LLMS_FULL)
    assert list(corpus) == ["doc:docs.lithosai.com/billing", "doc:docs.lithosai.com/usage"]
    assert corpus["doc:docs.lithosai.com/billing"]["cap"] == 2
    assert "reload" not in corpus["doc:docs.lithosai.com/usage"]
    assert llms_full_corpus("# Billing\n\nNo source lines.") == {}


def _pages(client, pages):
    fetched = []

    async def get_text(url, **kwargs):
        fetched.append(url)
        return pages.get(url)

    client._get_text = get_text
    return fetched


async def test_mintlify_distinct_ranks_the_page_in_llms_full():
    client = MintlifyClient()
    _pages(client, {"https://docs.lithosai.com/llms-full.txt": LLMS_FULL})
    site = "https://docs.lithosai.com/"
    doc = Doc("mintlify", f"{site}billing", "Billing", "x", "LithosAI", site=site)
    assert await client.distinct("LithosAI reload threshold monthly cap", doc)
    assert not await client.distinct("LithosAI usage limits", doc)
    await client.aclose()


async def test_sphinx_distinct_reads_the_site_searchindex():
    client = ApiDocsClient()
    site = "https://claripy.rtfd.io/en/latest/"
    _pages(client, {f"{site}searchindex.js": SEARCHINDEX})
    doc = Doc("api", f"{site}api.html", "claripy.eval", "x", "claripy", site=site)
    assert await client.distinct("claripy reload threshold", doc)
    assert not await client.distinct("claripy threshold cap", doc)
    await client.aclose()


ROOT = "https://docs.rs/miden-core-lib/latest/miden_core_lib/"
ALL = (
    '<li><a href="sorted_array/fn.lowerbound_key.html">a</a></li>'
    '<li><a href="sorted_array/fn.upperbound_key.html">b</a></li>'
    '<li><a href="hash/fn.digest.html">c</a></li>'
)


async def test_docsrs_distinct_compares_pages_with_similar_names():
    client = ApiDocsClient()
    gold = f"{ROOT}sorted_array/fn.lowerbound_key.html"
    pages = {
        f"{ROOT}all.html": ALL,
        gold: "<main>First key not less than the value in a sorted array.</main>",
        f"{ROOT}sorted_array/fn.upperbound_key.html": "<main>First key greater than value.</main>",
        f"{ROOT}hash/fn.digest.html": "<main>Digest of a key.</main>",
        ROOT: "<main>Core library.</main>",
    }
    fetched = _pages(client, pages)
    doc = Doc("api", gold, "lowerbound_key", "x", "miden-core-lib", site=ROOT)
    assert await client.distinct("miden-core-lib lower bound key not less sorted", doc)
    assert f"{ROOT}sorted_array/fn.upperbound_key.html" in fetched
    assert f"{ROOT}hash/fn.digest.html" not in fetched
    assert not await client.distinct("miden-core-lib first key greater than value", doc)
    await client.aclose()


async def test_fresh_distinct_compares_entries_of_the_same_feed():
    client = ChangelogClient()
    client.corpora["Vercel"] = {
        "doc:vercel.com/changelog/drives": terms("old text"),
        "doc:vercel.com/changelog/sdk": terms("Standalone SDKs for Blob storage"),
    }
    doc = Doc(
        "fresh",
        "https://vercel.com/changelog/drives",
        "Drives",
        "Drive-specific permissions and standalone SDKs.",
        "Vercel",
    )
    assert await client.distinct("Vercel drive-specific permissions", doc)
    assert not await client.distinct("Vercel standalone SDKs Blob", doc)
    await client.aclose()


async def test_github_distinct_needs_the_span_in_one_issue_only():
    client = GitHubClient()
    gold = "https://github.com/pandas-dev/pandas/issues/1"
    replies = {
        "1": [{"html_url": gold}],
        "2": [{"html_url": gold}, {"html_url": "https://github.com/pandas-dev/pandas/pull/2"}],
        "0": [],
    }
    asked = []

    async def request_json(method, url, **kwargs):
        asked.append(kwargs["params"]["q"])
        return {"items": replies[kwargs["params"]["q"][-2]]}, None

    client._request_json = request_json
    doc = Doc("issue", gold, "t", "x", "pandas-dev/pandas")
    assert await client.distinct('pandas "span 1"', doc)
    assert not await client.distinct('pandas "span 2"', doc)
    assert not await client.distinct('pandas "span 0"', doc)
    assert asked[0] == 'repo:pandas-dev/pandas "span 1"'
    await client.aclose()
