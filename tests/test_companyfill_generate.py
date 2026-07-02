from datetime import UTC, datetime

from keenbench.companyfill.generate import run_generate
from keenbench.companyfill.models import display_name

HOUR = datetime(2026, 7, 2, 14, tzinfo=UTC)


def _stmt(value, qualifiers=None, rank="normal"):
    return {
        "mainsnak": {"datavalue": {"value": value}},
        "qualifiers": qualifiers or {},
        "rank": rank,
    }


def _time_qual(pcode, time):
    return {pcode: [{"datavalue": {"value": {"time": time}}}]}


NVDA_CLAIMS = {
    "P169": [_stmt({"id": "Q_CEO"}, qualifiers=_time_qual("P580", "+1993-01-01T00:00:00Z"))],
    "P571": [_stmt({"time": "+1993-04-05T00:00:00Z"})],
    "P452": [_stmt({"id": "Q_IND"}), _stmt({"id": "Q_JUNK"})],
    "P856": [_stmt("https://www.nvidia.com/")],
    "P1128": [_stmt({"amount": "+36000"}, qualifiers=_time_qual("P585", "+2026-01-26T00:00:00Z"))],
    "P1278": [_stmt("549300MLUDYVRQOOXS22")],
}

LABELS = {
    "Q_CEO": ("Jensen Huang", ["Jen-Hsun Huang"]),
    "Q30": ("United States of America", ["USA", "US"]),
    "Q_IND": ("semiconductor industry", []),
    "Q_JUNK": ("Standard Industrial Classification", []),
}


class FakeWikidata:
    def __init__(self, qids=None, claims=None):
        self.qids = qids or {}
        self.claims = claims or {}

    async def resolve(self, name):
        return self.qids.get(name)

    async def entity(self, qid):
        return self.claims.get(qid, {})

    async def country_qid(self, claims):
        return "Q30" if claims else None

    async def labels_and_aliases(self, ids):
        return {q: LABELS[q] for q in ids if q in LABELS}


class FakeSec:
    def __init__(self, facts=None):
        self.facts = facts or {}

    async def companyfacts(self, cik):
        return self.facts.get(cik)


class FakeGleif:
    async def lei_by_name(self, name):
        return "GLEIF_LEI_00000000000X"


NVDA_SEED = {"ticker": "NVDA", "title": "NVIDIA Corp", "cik": 1045810}


def test_display_name():
    assert display_name("NVIDIA CORP") == "nvidia"
    assert display_name("Amazon.com, Inc.") == "amazon.com"
    assert display_name("AMAZON COM INC") == "amazon com"
    assert display_name("Salesforce, Inc.") == "salesforce"
    assert display_name("BERKSHIRE HATHAWAY INC") == "berkshire hathaway"


async def test_companyfill_rows_fields_and_gold():
    wd = FakeWikidata(qids={"NVIDIA Corp": "Q1"}, claims={"Q1": NVDA_CLAIMS})
    rows, stats = await run_generate(
        [NVDA_SEED],
        wikidata=wd,
        sec=None,
        gleif=None,
        suites=("companyfill",),
        hour_ts=HOUR,
        min_employee_year=2025,
    )
    by_field = {r["gold"]["field"]: r for r in rows}
    assert set(by_field) == {
        "ceo",
        "founded_year",
        "hq_country",
        "industry",
        "website",
        "employees",
        "lei",
        "ticker",
    }
    assert by_field["ceo"]["query_text"] == "nvidia ceo"
    assert by_field["ceo"]["gold"]["value"] == "Jensen Huang"
    assert by_field["ceo"]["gold"]["aliases"] == ["Jen-Hsun Huang"]
    assert by_field["founded_year"]["gold"]["value"] == 1993
    assert by_field["hq_country"]["gold"]["value"] == "United States of America"
    assert by_field["industry"]["gold"]["value"] == ["semiconductor"]
    assert by_field["website"]["gold"]["value"] == "nvidia.com"
    assert by_field["employees"]["gold"]["value"] == 36000
    assert by_field["lei"]["gold"]["value"] == "549300MLUDYVRQOOXS22"
    assert by_field["ticker"]["gold"]["value"] == "NVDA"
    origin = by_field["ceo"]["query_origin"]
    assert origin["bucket"] == "companyfill"
    assert origin["subcategory"] == "companyfill_ceo"
    assert origin["provenance"]["qid"] == "Q1"
    assert stats.companies == 1 and stats.resolved == 1 and stats.rows == len(rows)


async def test_rows_are_deterministic_for_same_hour():
    wd = FakeWikidata(qids={"NVIDIA Corp": "Q1"}, claims={"Q1": NVDA_CLAIMS})
    kwargs = {
        "wikidata": wd,
        "sec": None,
        "gleif": None,
        "suites": ("companyfill",),
        "hour_ts": HOUR,
        "min_employee_year": 2025,
    }
    rows1, _ = await run_generate([NVDA_SEED], **kwargs)
    rows2, _ = await run_generate([NVDA_SEED], **kwargs)
    assert rows1 == rows2
    assert all(r["query_id"].endswith("_2026-07-02T14") for r in rows1)


async def test_stale_employees_omitted():
    claims = dict(NVDA_CLAIMS)
    claims["P1128"] = [
        _stmt({"amount": "+22000"}, qualifiers=_time_qual("P585", "+2021-01-01T00:00:00Z"))
    ]
    wd = FakeWikidata(qids={"NVIDIA Corp": "Q1"}, claims={"Q1": claims})
    rows, _ = await run_generate(
        [NVDA_SEED],
        wikidata=wd,
        sec=None,
        gleif=None,
        suites=("companyfill",),
        hour_ts=HOUR,
        min_employee_year=2025,
    )
    assert "employees" not in {r["gold"]["field"] for r in rows}


async def test_unresolved_company_dropped_by_min_fields():
    wd = FakeWikidata()
    rows, stats = await run_generate(
        [NVDA_SEED],
        wikidata=wd,
        sec=None,
        gleif=None,
        suites=("companyfill",),
        hour_ts=HOUR,
        min_employee_year=2025,
    )
    assert rows == [] and stats.resolved == 0


async def test_single_letter_ticker_skipped():
    wd = FakeWikidata(qids={"Agilent Technologies Inc": "Q1"}, claims={"Q1": NVDA_CLAIMS})
    rows, _ = await run_generate(
        [{"ticker": "A", "title": "Agilent Technologies Inc", "cik": 1090872}],
        wikidata=wd,
        sec=None,
        gleif=None,
        suites=("companyfill",),
        hour_ts=HOUR,
        min_employee_year=2025,
    )
    fields = {r["gold"]["field"] for r in rows}
    assert fields and "ticker" not in fields


async def test_gleif_backfills_missing_lei():
    claims = {k: v for k, v in NVDA_CLAIMS.items() if k != "P1278"}
    wd = FakeWikidata(qids={"NVIDIA Corp": "Q1"}, claims={"Q1": claims})
    rows, _ = await run_generate(
        [NVDA_SEED],
        wikidata=wd,
        sec=None,
        gleif=FakeGleif(),
        suites=("companyfill",),
        hour_ts=HOUR,
        min_employee_year=2025,
    )
    lei_rows = [r for r in rows if r["gold"]["field"] == "lei"]
    assert lei_rows[0]["gold"]["value"] == "GLEIF_LEI_00000000000X"
    assert lei_rows[0]["query_origin"]["provenance"]["registry"] == "gleif"


async def test_seed_deduped_by_title():
    wd = FakeWikidata(qids={"Alphabet Inc.": "Q1"}, claims={"Q1": NVDA_CLAIMS})
    seed = [
        {"ticker": "GOOGL", "title": "Alphabet Inc.", "cik": 1652044},
        {"ticker": "GOOG", "title": "Alphabet Inc.", "cik": 1652044},
    ]
    rows, stats = await run_generate(
        seed,
        wikidata=wd,
        sec=None,
        gleif=None,
        suites=("companyfill",),
        hour_ts=HOUR,
        min_employee_year=2025,
    )
    assert stats.companies == 1
    tickers = [r["gold"]["value"] for r in rows if r["gold"]["field"] == "ticker"]
    assert tickers == ["GOOGL"]


def _fin_facts(concepts):
    units = {
        name: {
            "units": {
                "USD": [{"form": "10-K", "fp": "FY", "end": "2026-01-25", "val": val, "fy": 2026}]
            }
        }
        for name, val in concepts.items()
    }
    return units


async def test_financials_rows_pin_fiscal_year():
    facts = _fin_facts(
        {
            "Revenues": 130497000000,
            "NetIncomeLoss": 72880000000,
            "Assets": 111601000000,
            "StockholdersEquity": 79327000000,
        }
    )
    sec = FakeSec(facts={1045810: facts})
    rows, stats = await run_generate(
        [NVDA_SEED],
        wikidata=None,
        sec=sec,
        gleif=None,
        suites=("financials",),
        hour_ts=HOUR,
        min_employee_year=2025,
    )
    by_field = {r["gold"]["field"]: r for r in rows}
    assert set(by_field) == {"revenue", "net_income", "total_assets", "stockholders_equity"}
    assert by_field["revenue"]["query_text"] == "nvidia revenue fiscal year 2026"
    assert by_field["revenue"]["gold"]["value"] == 130497000000
    assert by_field["revenue"]["query_origin"]["bucket"] == "financials"
    assert stats.rows == 4


async def test_financials_below_min_fields_dropped():
    sec = FakeSec(facts={1045810: _fin_facts({"Revenues": 1, "Assets": 2})})
    rows, _ = await run_generate(
        [NVDA_SEED],
        wikidata=None,
        sec=sec,
        gleif=None,
        suites=("financials",),
        hour_ts=HOUR,
        min_employee_year=2025,
    )
    assert rows == []


async def test_company_exception_counted_not_raised():
    class BoomWikidata(FakeWikidata):
        async def resolve(self, name):
            raise RuntimeError("boom")

    rows, stats = await run_generate(
        [NVDA_SEED],
        wikidata=BoomWikidata(),
        sec=None,
        gleif=None,
        suites=("companyfill",),
        hour_ts=HOUR,
        min_employee_year=2025,
    )
    assert rows == [] and stats.errors == 1
