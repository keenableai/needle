import json

import pytest

from keenbench.companyfill import cli as companyfill_cli
from keenbench.companyfill.score import GoldQuery, first_hit_rank, run_answers
from keenbench.shared.search import SearchResult
from keenbench.shared.search import factory as search_factory

CEO_Q = GoldQuery(
    text="nvidia ceo",
    field="ceo",
    field_type="person",
    value="Jensen Huang",
    aliases=(),
    bucket="companyfill",
    freshness_window="1y",
)
EMP_Q = GoldQuery(
    text="nvidia number of employees",
    field="employees",
    field_type="numeric_band",
    value=36000,
    aliases=(),
    bucket="companyfill",
    freshness_window="1y",
)
REV_Q = GoldQuery(
    text="nvidia revenue fiscal year 2026",
    field="revenue",
    field_type="money",
    value=130497000000,
    aliases=(),
    bucket="financials",
    freshness_window="1y",
)


def _r(url, title=None, snippet=None):
    return SearchResult(url=url, title=title, snippet=snippet)


class FakeEngine:
    def __init__(self, canned):
        self.canned = canned
        self.closed = False

    async def search(self, query, *, num_results=10):
        return self.canned.get(query, ([], None))

    async def aclose(self):
        self.closed = True


def test_first_hit_rank_and_snippet_cap():
    results = [
        _r("https://a.com", "NVIDIA news", "GPU launch coverage"),
        _r("https://b.com", "About", "x" * 100 + " CEO Jensen Huang leads the company"),
    ]
    assert first_hit_rank(CEO_Q, results, snippet_chars=0) == 2
    assert first_hit_rank(CEO_Q, results, snippet_chars=50) is None


def test_field_cues_applied_from_spec():
    hit = [_r("https://a.com", None, "NVIDIA has 34,000 employees worldwide")]
    miss = [_r("https://a.com", None, "34,000 people work at the company")]
    assert first_hit_rank(EMP_Q, hit, snippet_chars=0) == 1
    assert first_hit_rank(EMP_Q, miss, snippet_chars=0) is None


async def test_run_answers_metrics_and_breakdowns():
    engine = FakeEngine(
        {
            CEO_Q.text: (
                [
                    _r("https://a.com", "NVIDIA", "GPU maker"),
                    _r("https://b.com", "Leadership", "CEO Jensen Huang"),
                ],
                None,
            ),
            REV_Q.text: (
                [_r("https://c.com", "10-K", "revenue of $130.5 billion for fiscal 2026")],
                None,
            ),
            EMP_Q.text: (None, {"error_type": "http_error", "error_message": "429"}),
        }
    )
    report = await run_answers([CEO_Q, REV_Q, EMP_Q], {"fake": engine}, num_results=5)
    e = report["engines"]["fake"]
    assert e["num_scored"] == 2
    assert e["search_errors"] == 1
    assert e["recall_at_k"] == 1.0
    assert e["mrr_at_k"] == pytest.approx((1 / 2 + 1 / 1) / 2)
    assert e["by_field"]["ceo"] == {"n": 1, "recall_at_k": 1.0}
    assert "employees" not in e["by_field"]
    assert e["by_bucket"]["financials"]["recall_at_k"] == 1.0
    assert e["by_freshness"]["1y"]["n"] == 2
    assert report["num_queries"] == 3


async def test_run_answers_zero_queries_and_all_errors():
    engine = FakeEngine({CEO_Q.text: (None, {"error_type": "transport", "error_message": "x"})})
    report = await run_answers([CEO_Q], {"fake": engine})
    e = report["engines"]["fake"]
    assert e["recall_at_k"] == 0.0 and e["mrr_at_k"] == 0.0 and e["num_scored"] == 0


def _write_rows(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _gold_row(field="ceo", field_type="person", value="Jensen Huang", origin_as_string=True):
    origin = {"bucket": "companyfill", "topical_domain": "finance"}
    return {
        "query_text": f"nvidia {field}",
        "query_origin": json.dumps(origin) if origin_as_string else origin,
        "gold": {
            "field": field,
            "field_type": field_type,
            "value": value,
            "aliases": [],
            "freshness_window": "1y",
        },
    }


def test_load_gold_rows_skips_rows_without_gold(tmp_path):
    f = tmp_path / "q.jsonl"
    _write_rows(f, [_gold_row(), {"query_text": "no gold"}, {"gold": {"field": "x"}}])
    rows = companyfill_cli._load_gold_rows(str(f))
    assert len(rows) == 1


def test_gold_query_parses_stringified_origin():
    q = companyfill_cli._gold_query(_gold_row())
    assert q.bucket == "companyfill" and q.field == "ceo" and q.value == "Jensen Huang"
    q2 = companyfill_cli._gold_query(_gold_row(origin_as_string=False))
    assert q2.bucket == "companyfill"


def test_run_rejects_missing_rows_and_bad_flags(tmp_path, monkeypatch):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n")
    with pytest.raises(SystemExit):
        companyfill_cli.Companyfill().run(queries=str(empty))

    f = tmp_path / "q.jsonl"
    _write_rows(f, [_gold_row(), _gold_row(field="website", field_type="domain", value="a.com")])
    with pytest.raises(SystemExit):
        companyfill_cli.Companyfill().run(queries=str(f), limit=1, sample="bogus")
    with pytest.raises(SystemExit):
        companyfill_cli.Companyfill().run(queries=str(f), engines="bing")
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        companyfill_cli.Companyfill().run(queries=str(f), engines="exa")


def test_generate_rejects_unknown_suite():
    with pytest.raises(SystemExit):
        companyfill_cli.Companyfill().generate(suites="bogus")


def test_run_passes_keenable_api_key_and_writes_report(tmp_path, monkeypatch):
    f = tmp_path / "q.jsonl"
    _write_rows(f, [_gold_row()])
    monkeypatch.setenv("KEENABLE_API_KEY", "kb-key")

    created = {}

    class FakeKeenable:
        def __init__(self, **kwargs):
            created.update(kwargs)

        async def aclose(self):
            pass

    async def fake_run_answers(queries, clients, **kwargs):
        return {"num_queries": len(queries), "num_results": 5, "snippet_chars": 500, "engines": {}}

    monkeypatch.setattr(search_factory, "KeenableClient", FakeKeenable)
    monkeypatch.setattr(companyfill_cli, "run_answers", fake_run_answers)
    out = tmp_path / "report.json"
    companyfill_cli.Companyfill().run(queries=str(f), engines="keenable", out=str(out))
    assert created == {"api_key": "kb-key", "mode": "pro"}
    assert json.loads(out.read_text())["num_queries"] == 1


def test_run_stratified_sampling_by_field(tmp_path, monkeypatch):
    rows = [_gold_row()] * 6 + [_gold_row(field="website", field_type="domain", value="a.com")] * 6
    f = tmp_path / "q.jsonl"
    _write_rows(f, rows)
    monkeypatch.delenv("KEENABLE_API_KEY", raising=False)

    seen = {}

    async def fake_run_answers(queries, clients, **kwargs):
        seen["fields"] = sorted({q.field for q in queries})
        seen["n"] = len(queries)
        return {"num_queries": len(queries), "num_results": 5, "snippet_chars": 500, "engines": {}}

    class FakeKeenable:
        def __init__(self, **kwargs):
            pass

        async def aclose(self):
            pass

    monkeypatch.setattr(search_factory, "KeenableClient", FakeKeenable)
    monkeypatch.setattr(companyfill_cli, "run_answers", fake_run_answers)
    companyfill_cli.Companyfill().run(
        queries=str(f), engines="keenable", limit=4, out=str(tmp_path / "r.json")
    )
    assert seen["n"] == 4
    assert seen["fields"] == ["ceo", "website"]
