from keenbench.finance.score import GoldFinance, extract_adshes, run_finance
from keenbench.shared.search import SearchResult


def _r(url: str, title: str = "", snippet: str = "") -> SearchResult:
    return SearchResult(url=url, title=title, snippet=snippet)


def test_extract_adshes_from_url_and_text():
    result = _r(
        "https://www.sec.gov/Archives/edgar/data/497/000000497725000067/aflac8k.htm",
        snippet="Accession No. 0001193125-26-039415",
    )
    found = extract_adshes(result, snippet_chars=500)
    assert "000000497725000067" in found
    assert "000119312526039415" in found


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


ANSWER = GoldFinance(
    text="acme q1 fiscal 2026 net income",
    kind="answer",
    bucket="filings",
    syntax="plain",
    field="net_income",
    field_type="money",
    value=16599000000.0,
    tier="mega",
)
ITEM = GoldFinance(
    text='aflac "video presentation" 8-K',
    kind="item",
    bucket="filingdoc",
    syntax="quoted",
    adsh="000000497725000067",
    form="8-K",
    tier="mega",
)


async def test_run_finance_scores_answer_containment():
    hit = _r("https://stockanalysis.com/acme", snippet="Net income of $16.6 billion in Q1")
    miss = _r("https://example.com", snippet="no numbers here")
    report = await run_finance([ANSWER], {"good": FakeEngine([miss, hit])})
    e = report["engines"]["good"]
    assert e["recall_at_k"] == 1.0
    assert e["mrr_at_k"] == 0.5
    assert e["by_field"]["net_income"]["recall_at_k"] == 1.0
    assert e["by_tier"]["mega"]["recall_at_k"] == 1.0


async def test_run_finance_scores_item_identity():
    hit = _r("https://www.sec.gov/Archives/edgar/data/497/000000497725000067/x.htm")
    report = await run_finance(
        [ITEM], {"good": FakeEngine([hit]), "bad": FakeEngine([_r("https://example.com")])}
    )
    assert report["engines"]["good"]["recall_at_k"] == 1.0
    assert report["engines"]["good"]["by_bucket"]["filingdoc"]["recall_at_k"] == 1.0
    assert report["engines"]["bad"]["misses_system_specific"] == 1


async def test_run_finance_answer_rejects_out_of_band_amounts():
    close_but_wrong = _r("https://x.com", snippet="Net income of $18 billion in Q1")
    report = await run_finance([ANSWER], {"e": FakeEngine([close_but_wrong])})
    assert report["engines"]["e"]["recall_at_k"] == 0.0
