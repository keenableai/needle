from needle.finance.registries import (
    GleifClient,
    SecClient,
    WikidataClient,
    current_ceo,
    employees,
    founded_year,
    lei,
    website,
)


def _stmt(value, qualifiers=None, rank="normal"):
    return {
        "mainsnak": {"datavalue": {"value": value}},
        "qualifiers": qualifiers or {},
        "rank": rank,
    }


def _time_qual(pcode, time):
    return {pcode: [{"datavalue": {"value": {"time": time}}}]}


def test_current_ceo_skips_ended_and_prefers_latest_start():
    claims = {
        "P169": [
            _stmt({"id": "Q_OLD"}, qualifiers=_time_qual("P582", "+2020-01-01T00:00:00Z")),
            _stmt({"id": "Q_NEW"}, qualifiers=_time_qual("P580", "+2023-02-01T00:00:00Z")),
            _stmt({"id": "Q_MID"}, qualifiers=_time_qual("P580", "+2019-02-01T00:00:00Z")),
        ]
    }
    assert current_ceo(claims) == ("Q_NEW", 2023)


def test_current_ceo_preferred_rank_wins():
    claims = {
        "P169": [
            _stmt({"id": "Q_A"}, qualifiers=_time_qual("P580", "+2024-01-01T00:00:00Z")),
            _stmt({"id": "Q_B"}, rank="preferred"),
        ]
    }
    assert current_ceo(claims) == ("Q_B", None)
    assert current_ceo({}) == (None, None)


def test_current_ceo_skips_deprecated_rank():
    claims = {
        "P169": [
            _stmt(
                {"id": "Q_WRONG"},
                qualifiers=_time_qual("P580", "+2025-01-01T00:00:00Z"),
                rank="deprecated",
            ),
            _stmt({"id": "Q_RIGHT"}, qualifiers=_time_qual("P580", "+2020-01-01T00:00:00Z")),
        ]
    }
    assert current_ceo(claims) == ("Q_RIGHT", 2020)


def test_scalar_extractors():
    claims = {
        "P571": [_stmt({"time": "+1993-04-05T00:00:00Z"})],
        "P856": [_stmt("https://www.nvidia.com/")],
        "P1278": [_stmt("549300MLUDYVRQOOXS22")],
        "P1128": [
            _stmt({"amount": "+22473"}, qualifiers=_time_qual("P585", "+2021-01-01T00:00:00Z")),
            _stmt({"amount": "+36000"}, qualifiers=_time_qual("P585", "+2026-01-26T00:00:00Z")),
        ],
    }
    assert founded_year(claims) == 1993
    assert website(claims) == "https://www.nvidia.com/"
    assert lei(claims) == "549300MLUDYVRQOOXS22"
    assert employees(claims) == (36000, 2026)


def _canned(payloads):
    calls = []

    async def fake(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return payloads.pop(0), None

    return fake, calls


async def test_sec_tickers_parses_and_caches(monkeypatch):
    c = SecClient()
    payload = {
        "0": {"cik_str": 320193, "ticker": "aapl", "title": "Apple Inc."},
        "1": {"cik_str": 0, "ticker": "", "title": "No Ticker Co"},
        "2": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
    }
    fake, calls = _canned([payload])
    monkeypatch.setattr(c, "_request_json", fake)
    rows = await c.tickers()
    assert rows == [
        {"ticker": "AAPL", "title": "Apple Inc.", "cik": 320193},
        {"ticker": "NVDA", "title": "NVIDIA CORP", "cik": 1045810},
    ]
    assert await c.tickers(limit=1) == rows[:1]
    assert len(calls) == 1
    assert c.default_headers["User-Agent"].startswith("needle/")


async def test_sec_companyfacts_extracts_us_gaap(monkeypatch):
    c = SecClient()
    fake, _ = _canned([{"facts": {"us-gaap": {"Assets": {}}}}, {"facts": {}}])
    monkeypatch.setattr(c, "_request_json", fake)
    assert await c.companyfacts(320193) == {"Assets": {}}
    assert await c.companyfacts(1) is None


async def test_wikidata_entity_caches(monkeypatch):
    c = WikidataClient()
    payload = {"entities": {"Q1": {"claims": {"P571": []}}}}
    fake, calls = _canned([payload])
    monkeypatch.setattr(c, "_request_json", fake)
    assert await c.entity("Q1") == {"P571": []}
    assert await c.entity("Q1") == {"P571": []}
    assert len(calls) == 1


async def test_wikidata_resolve_gates_on_company_signals(monkeypatch):
    c = WikidataClient()

    async def fake_get(url, params=None, headers=None):
        return {"search": [{"id": "Q_HUMAN"}, {"id": "Q_CO"}]}

    entities = {
        "Q_HUMAN": {"P31": [_stmt({"id": "Q5"})]},
        "Q_CO": {"P31": [_stmt({"id": "Q783794"})]},
    }

    async def fake_entity(qid):
        return entities[qid]

    monkeypatch.setattr(c, "_get", fake_get)
    monkeypatch.setattr(c, "entity", fake_entity)
    assert await c.resolve("acme") == "Q_CO"


async def test_wikidata_resolve_accepts_lei_signal(monkeypatch):
    c = WikidataClient()

    async def fake_get(url, params=None, headers=None):
        return {"search": [{"id": "Q_X"}]}

    async def fake_entity(qid):
        return {"P1278": [_stmt("LEI123")]}

    monkeypatch.setattr(c, "_get", fake_get)
    monkeypatch.setattr(c, "entity", fake_entity)
    assert await c.resolve("acme") == "Q_X"


async def test_wikidata_country_falls_back_to_hq_location(monkeypatch):
    c = WikidataClient()

    async def fake_entity(qid):
        assert qid == "Q_SC"
        return {"P17": [_stmt({"id": "Q30"})]}

    monkeypatch.setattr(c, "entity", fake_entity)
    assert await c.country_qid({"P17": [_stmt({"id": "Q30"})]}) == "Q30"
    assert await c.country_qid({"P159": [_stmt({"id": "Q_SC"})]}) == "Q30"
    assert await c.country_qid({}) is None


async def test_wikidata_labels_and_aliases(monkeypatch):
    c = WikidataClient()
    payload = {
        "entities": {
            "Q2": {
                "labels": {"en": {"value": "Tim Cook"}},
                "aliases": {"en": [{"value": "Timothy Donald Cook"}]},
            },
            "Q3": {"labels": {}},
        }
    }
    fake, _ = _canned([payload])
    monkeypatch.setattr(c, "_request_json", fake)
    out = await c.labels_and_aliases(["Q2", "Q3", "Q2", ""])
    assert out == {"Q2": ("Tim Cook", ["Timothy Donald Cook"])}


async def test_gleif_exact_name_match_only(monkeypatch):
    c = GleifClient()
    payload = {
        "data": [
            {
                "id": "X1",
                "attributes": {
                    "lei": "LEI_OTHER",
                    "entity": {"legalName": {"name": "Apple Bank"}},
                },
            },
            {
                "id": "X2",
                "attributes": {
                    "lei": "LEI_APPLE",
                    "entity": {"legalName": {"name": "Apple Inc."}},
                },
            },
        ]
    }
    fake, _ = _canned([payload, dict(payload)])
    monkeypatch.setattr(c, "_request_json", fake)
    assert await c.lei_by_name("apple inc.") == "LEI_APPLE"
    assert await c.lei_by_name("Apple") is None
