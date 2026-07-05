from collections import Counter
from datetime import UTC, datetime

from keenbench.finance.generate import run_generate, tiered_companies

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)
HOUR = NOW.replace(minute=0)


def _quarterly(val, start, end, fy, fp):
    return {"val": val, "start": start, "end": end, "fy": fy, "fp": fp, "form": "10-Q"}


class FakeSec:
    def __init__(self, facts_by_cik):
        self._facts = facts_by_cik

    async def companyfacts(self, cik):
        return self._facts.get(cik)


class FakeEdgar:
    def __init__(self, filings_by_cik, texts):
        self._filings = filings_by_cik
        self._texts = texts

    async def filings(self, cik, *, forms, limit=40):
        return [f for f in self._filings.get(cik, []) if f["form"] in forms]

    async def document_text(self, filing):
        return self._texts.get(filing.adsh)


class FakeLLM:
    def __init__(self, reply):
        self._reply = reply

    async def complete(self, prompt, *, max_tokens, reasoning_effort):
        return self._reply, None


SEED_ROWS = [
    {"ticker": "AAA", "title": "Acme Corp", "cik": 1, "tier": "mega"},
    {"ticker": "BBB", "title": "Bolt Industries Inc", "cik": 2, "tier": "mid"},
]

FACTS = {
    1: {
        "NetIncomeLoss": {
            "units": {"USD": [_quarterly(100e6, "2026-01-01", "2026-03-31", 2026, "Q1")]}
        }
    },
    2: {
        "OperatingIncomeLoss": {
            "units": {"USD": [_quarterly(50e6, "2026-01-01", "2026-03-31", 2026, "Q1")]}
        }
    },
}


async def test_filings_rows_pin_quarter_and_tier():
    rows, stats = await run_generate(
        sec=FakeSec(FACTS),
        edgar=None,
        llm=None,
        seed_rows=SEED_ROWS,
        hour_ts=HOUR,
        now=NOW,
        fields=("net_income", "operating_income"),
        per_company=1,
        quarters_back=4,
        filingdoc_target=0,
        seed=0,
    )
    assert stats.filings_rows == 2
    by_field = {r["gold"]["field"]: r for r in rows}
    assert "q1 fiscal 2026" in by_field["net_income"]["query_text"]
    assert by_field["net_income"]["gold"]["tier"] == "mega"
    assert by_field["operating_income"]["gold"]["tier"] == "mid"
    syntaxes = Counter(r["query_origin"]["syntax"] for r in rows)
    assert syntaxes["plain"] == 1 and syntaxes["quoted"] == 1


DOC_TEXT = (
    "Acme Corp announced the acquisition of Riverbend Analytics for $250 million "
    "in cash, expanding its data platform business across Europe."
)


async def test_filingdoc_rows_carry_accession_gold():
    filings = {
        1: [
            {
                "adsh": "0000000001-26-000001",
                "form": "8-K",
                "filed": "2026-06-01",
                "primary_doc": "x.htm",
            }
        ]
    }
    rows, stats = await run_generate(
        sec=None,
        edgar=FakeEdgar(filings, {"0000000001-26-000001": DOC_TEXT * 30}),
        llm=FakeLLM('Acme "acquisition of Riverbend Analytics" 250 million'),
        seed_rows=[SEED_ROWS[0]],
        hour_ts=HOUR,
        now=NOW,
        fields=("net_income",),
        per_company=0,
        quarters_back=4,
        filingdoc_target=1,
        seed=0,
    )
    assert stats.filingdoc_rows == 1
    assert rows[0]["gold"]["ids"]["adsh"] == "000000000126000001"
    assert rows[0]["query_origin"]["bucket"] == "filingdoc"


async def test_filingdoc_rejects_query_without_verbatim_span():
    filings = {
        1: [
            {
                "adsh": "0000000001-26-000001",
                "form": "8-K",
                "filed": "2026-06-01",
                "primary_doc": "x.htm",
            }
        ]
    }
    rows, stats = await run_generate(
        sec=None,
        edgar=FakeEdgar(filings, {"0000000001-26-000001": DOC_TEXT * 30}),
        llm=FakeLLM('Acme "not a verbatim span" 250 million'),
        seed_rows=[SEED_ROWS[0]],
        hour_ts=HOUR,
        now=NOW,
        fields=("net_income",),
        per_company=0,
        quarters_back=4,
        filingdoc_target=1,
        seed=0,
    )
    assert stats.filingdoc_rows == 0
    assert stats.doc_rejected == 1


def test_tiered_companies_samples_each_band():
    all_rows = [{"ticker": f"T{i}", "title": f"Company {i}", "cik": i} for i in range(3000)]
    picked = tiered_companies(all_rows, 5, seed=0)
    tiers = Counter(r["tier"] for r in picked)
    assert tiers == {"mega": 5, "large": 5, "mid": 5}
    assert all(r["cik"] < 100 for r in picked if r["tier"] == "mega")
    assert all(500 <= r["cik"] < 2500 for r in picked if r["tier"] == "mid")
