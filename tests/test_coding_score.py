from needle.coding.score import GoldCoding, extract_page_keys, page_match, run_coding
from needle.shared.search import SearchResult

PAGE = "docs.example.com/features/batch-scrape"


def _r(url: str, title: str = "", snippet: str = "") -> SearchResult:
    return SearchResult(url=url, title=title, snippet=snippet)


def test_extract_page_urls():
    slug = extract_page_keys(_r(f"https://{PAGE}"), snippet_chars=500)
    assert slug.pages == {PAGE}
    trailing = extract_page_keys(_r(f"https://{PAGE}/"), snippet_chars=500)
    assert PAGE in trailing.pages
    markdown = extract_page_keys(_r(f"https://{PAGE}.md"), snippet_chars=500)
    assert PAGE in markdown.pages
    insecure = extract_page_keys(_r(f"http://{PAGE}"), snippet_chars=500)
    assert PAGE in insecure.pages
    translated = extract_page_keys(
        _r("https://docs.example.com/fr/features/batch-scrape"), snippet_chars=500
    )
    assert PAGE not in translated.pages
    query = extract_page_keys(_r(f"https://{PAGE}?x=1#section"), snippet_chars=500)
    assert PAGE in query.pages
    child = extract_page_keys(_r(f"https://{PAGE}/options"), snippet_chars=500)
    assert child.pages == {f"{PAGE}/options"}
    other_version = extract_page_keys(
        _r("https://docs.example.com/v1/features/batch-scrape"), snippet_chars=500
    )
    assert PAGE not in other_version.pages


def test_a_url_in_the_title_is_not_a_hit():
    keys = extract_page_keys(
        _r("https://example.com/mirror", title=f"see https://{PAGE}", snippet="unrelated guide"),
        snippet_chars=500,
    )
    assert PAGE not in keys.pages


def test_path_case_is_part_of_the_page():
    keys = extract_page_keys(_r("https://docs.example.com/Foo/Bar"), snippet_chars=500)
    assert "docs.example.com/Foo/Bar" in keys.pages
    assert PAGE not in keys.pages
    gold = GoldCoding(text="q", item_key=PAGE, bucket="title", page_key=PAGE)
    assert not page_match(gold, keys)


def test_extract_page_from_snippet_only():
    keys = extract_page_keys(
        _r(
            "https://example.com/mirror",
            title="a guide",
            snippet=f"see https://{PAGE}.md for the writeup",
        ),
        snippet_chars=500,
    )
    assert PAGE in keys.pages
    gold = GoldCoding(text="q", item_key=PAGE, bucket="task", page_key=PAGE)
    assert page_match(gold, keys)


def test_page_match_is_the_page_not_a_neighbor():
    gold = GoldCoding(text="q", item_key=PAGE, bucket="title", page_key=PAGE)
    hit = extract_page_keys(_r(f"https://{PAGE}"), snippet_chars=500)
    other = extract_page_keys(
        _r("https://docs.example.com/features/batch-scrape-extra"), snippet_chars=500
    )
    assert page_match(gold, hit)
    assert not page_match(gold, other)


class FakeEngine:
    def __init__(self, results, error=None):
        self._results = results
        self._error = error
        self.latencies_ms = [10.0]

    async def search(self, query, *, num_results=10):
        if self._error is not None:
            return None, self._error
        return self._results, None

    async def aclose(self):
        pass


GOLD = [
    GoldCoding(
        text="Firecrawl Batch Scrape",
        item_key=PAGE,
        bucket="title",
        page_key=PAGE,
        product="Firecrawl",
    ),
    GoldCoding(
        text="example plan caps and burst windows for api requests",
        item_key="docs.example.com/rate-limits",
        bucket="task",
        page_key="docs.example.com/rate-limits",
        product="Example",
    ),
]


async def test_run_coding_scores_hits_and_breakdowns():
    hit_title = _r(f"https://{PAGE}")
    hit_task = _r("https://docs.example.com/rate-limits")
    report = await run_coding(
        GOLD, {"good": FakeEngine([hit_title, hit_task]), "empty": FakeEngine([])}
    )
    good = report["engines"]["good"]
    assert good["recall_at_k"] == 1.0
    first, second = good["per_query"][0]["results"]
    assert first["matched"] is True
    assert second["matched"] is False
    assert good["by_bucket"]["title"]["recall_at_k"] == 1.0
    assert good["by_bucket"]["task"]["recall_at_k"] == 1.0
    assert good["by_product"]["Firecrawl"]["n"] == 1
    empty = report["engines"]["empty"]
    assert empty["recall_at_k"] == 0.0
    assert empty["misses_system_specific"] == 2
    assert empty["misses_universal"] == 0


async def test_run_coding_classifies_misses():
    hit = _r(f"https://{PAGE}")
    other = _r("https://docs.example.com/v1/features/batch-scrape")
    report = await run_coding([GOLD[0]], {"good": FakeEngine([hit]), "bad": FakeEngine([other])})
    assert report["engines"]["bad"]["misses_system_specific"] == 1
    errored = await run_coding([GOLD[0]], {"err": FakeEngine([], error={"error_type": "http"})})
    assert errored["engines"]["err"]["num_scored"] == 0
    assert errored["engines"]["err"]["search_errors"] == 1
    assert errored["engines"]["err"]["recall_at_k"] == 0.0


async def test_run_coding_ultimate_row():
    hit = _r(f"https://{PAGE}")
    report = await run_coding(
        [GOLD[0]],
        {"good": FakeEngine([hit]), "bad": FakeEngine([_r("https://example.com/x")])},
    )
    ult = report["engines"]["ultimate"]
    assert ult["recall_at_k"] == 1.0
    assert ult["mrr_at_k"] is None
    pq = ult["per_query"][0]
    assert pq["hit_rank"] == 1
    assert pq["item_key"] == PAGE
    assert pq["results"][0]["url"] == hit.url
