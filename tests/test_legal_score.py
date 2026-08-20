from needle.legal.score import (
    GoldLegal,
    extract_legal_ids,
    ids_match,
    norm_citation,
    run_legal,
)
from needle.shared.search import SearchResult


def _r(url: str, title: str = "", snippet: str = "") -> SearchResult:
    return SearchResult(url=url, title=title, snippet=snippet)


def test_norm_citation():
    assert norm_citation("89 F.4th 1188") == "89:f4th:1188"
    assert norm_citation("598 U.S. 471") == "598:us:471"
    assert norm_citation("143 S. Ct. 2028") == "143:sct:2028"
    assert norm_citation("no citation") is None


def test_extract_cluster_and_justia_urls():
    ids = extract_legal_ids(
        _r("https://www.courtlistener.com/opinion/10865557/fresh-mix/"), snippet_chars=500
    )
    assert "10865557" in ids.clusters
    ids = extract_legal_ids(
        _r("https://supreme.justia.com/cases/federal/us/598/471/"), snippet_chars=500
    )
    assert "598:us:471" in ids.cites
    ids = extract_legal_ids(
        _r("https://law.justia.com/cases/federal/appellate-courts/ca9/25-2462/x.html"),
        snippet_chars=500,
    )
    assert "25-2462" in ids.dockets


def test_extract_citation_and_docket_from_text():
    ids = extract_legal_ids(
        _r(
            "https://example.com/x",
            title="Smith v. Jones, 89 F.4th 1188 (9th Cir. 2024)",
            snippet="No. 21-50031 argued before the panel",
        ),
        snippet_chars=500,
    )
    assert "89:f4th:1188" in ids.cites
    assert "21-50031" in ids.dockets


def test_extract_cfr_citations():
    ids = extract_legal_ids(
        _r(
            "https://www.law.cornell.edu/cfr/text/17/240.10b-5",
            snippet="See 21 C.F.R. § 520.1315 for dosage.",
        ),
        snippet_chars=500,
    )
    assert "17:240.10b-5" in ids.cfr
    assert "21:520.1315" in ids.cfr


def test_docket_match_requires_party_token():
    gold = GoldLegal(
        text="q",
        case_key="1",
        bucket="caselaw",
        syntax="plain",
        docket="25-2462",
        party_tokens=("pisanelli",),
    )
    result = _r("https://example.com", snippet="Docket No. 25-2462 Pisanelli Bice appeal")
    found = extract_legal_ids(result, snippet_chars=500)
    assert ids_match(gold, found, result_text="docket no. 25-2462 pisanelli bice appeal")
    assert not ids_match(gold, found, result_text="docket no. 25-2462 something unrelated")
    assert not ids_match(gold, found, result_text="docket no. 25-2462 pisanellian appeal")


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
    GoldLegal(
        text="fresh mix v pisanelli bice ninth circuit",
        case_key="10865557",
        bucket="caselaw",
        syntax="plain",
        cluster="10865557",
        docket="25-2462",
        party_tokens=("pisanelli",),
        court="ca9",
    ),
    GoldLegal(
        text='securities fraud "artifice to defraud" site:law.cornell.edu',
        case_key="17:240.10b-5",
        bucket="code",
        syntax="site",
        cfr="17:240.10b-5",
    ),
]


async def test_run_legal_scores_hits_and_breakdowns():
    hit_case = _r("https://www.courtlistener.com/opinion/10865557/fresh-mix/")
    hit_code = _r("https://www.law.cornell.edu/cfr/text/17/240.10b-5")
    report = await run_legal(
        GOLD, {"good": FakeEngine([hit_case, hit_code]), "empty": FakeEngine([])}
    )
    good = report["engines"]["good"]
    assert good["recall_at_k"] == 1.0
    first, second = good["per_query"][0]["results"]
    assert first["matched"] is True and first["snippet"] == ""
    assert second["matched"] is False
    assert good["by_bucket"]["caselaw"]["recall_at_k"] == 1.0
    assert good["by_syntax"]["site"]["recall_at_k"] == 1.0
    assert good["by_court"]["ca9"]["n"] == 1
    empty = report["engines"]["empty"]
    assert empty["recall_at_k"] == 0.0
    assert empty["misses_system_specific"] == 2
    assert empty["misses_universal"] == 0


async def test_run_legal_classifies_misses():
    hit = _r("https://www.courtlistener.com/opinion/10865557/fresh-mix/")
    other = _r("https://example.com/nothing", snippet="irrelevant")
    report = await run_legal([GOLD[0]], {"good": FakeEngine([hit]), "bad": FakeEngine([other])})
    assert report["engines"]["bad"]["misses_system_specific"] == 1
    errored = await run_legal([GOLD[0]], {"err": FakeEngine([], error={"error_type": "http"})})
    assert errored["engines"]["err"]["num_scored"] == 1
    assert errored["engines"]["err"]["search_errors"] == 1
    assert errored["engines"]["err"]["recall_at_k"] == 0.0


async def test_run_legal_ultimate_row():
    hit = _r("https://www.courtlistener.com/opinion/10865557/fresh-mix/")
    report = await run_legal(
        [GOLD[0]],
        {"good": FakeEngine([hit]), "bad": FakeEngine([_r("https://example.com/x")])},
    )
    ult = report["engines"]["ultimate"]
    assert ult["recall_at_k"] == 1.0
    assert ult["mrr_at_k"] is None
    pq = ult["per_query"][0]
    assert pq["hit_rank"] == 1
    assert pq["results"][0]["url"] == hit.url
    assert pq["n_results"] == 2
