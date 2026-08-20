import json

import pytest

from keenbench.finance import cli as finance_cli
from keenbench.finance.score import GoldQuery, result_answers, run_answers
from keenbench.shared.cli import load_gold_rows
from keenbench.shared.search import DEFAULT_SNIPPET_CHARS, SearchResult
from keenbench.shared.search import factory as search_factory


def _load_gold_rows(path):
    return load_gold_rows(path, bench="finance", gold_ok=finance_cli._gold_ok)


CEO_Q = GoldQuery(
    text="nvidia ceo",
    field="ceo",
    field_type="person",
    value="Jensen Huang",
    aliases=(),
    bucket="finance",
    freshness_window="1y",
)
EMP_Q = GoldQuery(
    text="nvidia number of employees",
    field="employees",
    field_type="numeric_band",
    value=36000,
    aliases=(),
    bucket="finance",
    freshness_window="1y",
)
REV_Q = GoldQuery(
    text="nvidia q1 fiscal 2026 revenue",
    field="revenue",
    field_type="money",
    value=130497000000,
    aliases=(),
    bucket="filings",
    freshness_window="1y",
    syntax="plain",
    tier="mega",
)
FILINGDOC_Q = GoldQuery(
    text='aflac "video presentation" 8-K',
    field="filing",
    field_type="exact_id",
    value="000000497725000067",
    aliases=("0000004977-25-000067",),
    bucket="filingdoc",
    freshness_window="static",
    syntax="quoted",
    tier="mega",
)


def _r(url, title=None, snippet=None):
    return SearchResult(url=url, title=title, snippet=snippet)


class FakeEngine:
    def __init__(self, canned):
        self.canned = canned
        self.closed = False
        self.latencies_ms = []

    async def search(self, query, *, num_results=10):
        return self.canned.get(query, ([], None))

    async def aclose(self):
        self.closed = True


def test_result_answers_and_snippet_cap():
    miss = _r("https://a.com", "NVIDIA news", "GPU launch coverage")
    hit = _r("https://b.com", "About", "x" * 100 + " CEO Jensen Huang leads the company")
    assert result_answers(CEO_Q, miss, snippet_chars=0) is False
    assert result_answers(CEO_Q, hit, snippet_chars=0) is True
    assert result_answers(CEO_Q, hit, snippet_chars=50) is False


def test_field_cues_applied_from_spec():
    hit = _r("https://a.com", None, "NVIDIA has 34,000 employees worldwide")
    miss = _r("https://a.com", None, "34,000 people work at the company")
    assert result_answers(EMP_Q, hit, snippet_chars=0) is True
    assert result_answers(EMP_Q, miss, snippet_chars=0) is False


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
    assert e["num_scored"] == 3
    assert e["search_errors"] == 1
    assert e["recall_at_k"] == pytest.approx(2 / 3)
    assert e["mrr_at_k"] == pytest.approx((1 / 2 + 1 / 1) / 3)
    assert e["by_field"]["ceo"] == {"n": 1, "recall_at_k": 1.0}
    assert e["by_field"]["employees"] == {"n": 1, "recall_at_k": 0.0}
    assert e["by_bucket"]["filings"]["recall_at_k"] == 1.0
    assert e["by_freshness"]["1y"]["n"] == 3
    assert report["num_queries"] == 3


async def test_run_answers_scores_filingdoc_by_accession_in_url():
    hit = _r("https://www.sec.gov/Archives/edgar/data/497/000000497725000067/x.htm")
    engine = FakeEngine({FILINGDOC_Q.text: ([hit], None)})
    bad = FakeEngine({FILINGDOC_Q.text: ([_r("https://example.com")], None)})
    report = await run_answers([FILINGDOC_Q], {"good": engine, "bad": bad})
    good = report["engines"]["good"]
    assert good["recall_at_k"] == 1.0
    assert good["by_bucket"]["filingdoc"]["recall_at_k"] == 1.0
    assert good["by_syntax"]["quoted"]["recall_at_k"] == 1.0
    assert good["by_tier"]["mega"]["recall_at_k"] == 1.0
    assert report["engines"]["bad"]["misses_system_specific"] == 1


async def test_run_answers_zero_queries_and_all_errors():
    engine = FakeEngine({CEO_Q.text: (None, {"error_type": "transport", "error_message": "x"})})
    report = await run_answers([CEO_Q], {"fake": engine})
    e = report["engines"]["fake"]
    assert e["recall_at_k"] == 0.0 and e["mrr_at_k"] == 0.0 and e["num_scored"] == 1


async def test_run_answers_reports_latency():
    timed = FakeEngine({})
    timed.latencies_ms = [50.0]
    report = await run_answers([CEO_Q], {"timed": timed, "plain": FakeEngine({})})
    assert report["engines"]["timed"]["latency"] == {
        "n": 1,
        "mean_ms": 50.0,
        "p50_ms": 50.0,
        "p95_ms": 50.0,
        "samples_ms": [50.0],
    }
    assert report["engines"]["plain"]["latency"] is None


def _write_rows(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _gold_row(field="ceo", field_type="person", value="Jensen Huang", origin_as_string=True):
    origin = {"bucket": "finance", "topical_domain": "finance"}
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
    rows = _load_gold_rows(str(f))
    assert len(rows) == 1


def test_load_gold_rows_rejects_unknown_field_type(tmp_path):
    f = tmp_path / "q.jsonl"
    _write_rows(f, [_gold_row(field_type="bogus")])
    with pytest.raises(SystemExit, match="unsupported gold.field_type 'bogus'"):
        _load_gold_rows(str(f))


def test_gold_query_parses_stringified_origin():
    q = finance_cli._gold_query(_gold_row())
    assert q.bucket == "finance" and q.field == "ceo" and q.value == "Jensen Huang"
    q2 = finance_cli._gold_query(_gold_row(origin_as_string=False))
    assert q2.bucket == "finance"


def test_run_rejects_missing_rows_and_bad_flags(tmp_path, monkeypatch):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n")
    with pytest.raises(SystemExit):
        finance_cli.Finance().run(queries=str(empty))

    f = tmp_path / "q.jsonl"
    _write_rows(f, [_gold_row(), _gold_row(field="website", field_type="domain", value="a.com")])
    with pytest.raises(SystemExit):
        finance_cli.Finance().run(queries=str(f), limit=1, sample="bogus")
    with pytest.raises(SystemExit):
        finance_cli.Finance().run(queries=str(f), engines="bing")
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        finance_cli.Finance().run(queries=str(f), engines="exa")


def test_generate_rejects_unknown_suite():
    with pytest.raises(SystemExit):
        finance_cli.Finance().generate(suites="bogus")


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
    monkeypatch.setattr(finance_cli, "run_answers", fake_run_answers)
    out = tmp_path / "report.json"
    finance_cli.Finance().run(queries=str(f), engines="keenable", out=str(out))
    assert created == {
        "api_key": "kb-key",
        "mode": "pro",
        "snippet_chars": DEFAULT_SNIPPET_CHARS,
    }
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
    monkeypatch.setattr(finance_cli, "run_answers", fake_run_answers)
    finance_cli.Finance().run(
        queries=str(f), engines="keenable", limit=4, out=str(tmp_path / "r.json")
    )
    assert seen["n"] == 4
    assert seen["fields"] == ["ceo", "website"]


async def test_run_answers_ultimate_pools_hits_across_engines():
    good = FakeEngine({CEO_Q.text: ([_r("https://b.com", "Leadership", "CEO Jensen Huang")], None)})
    bad = FakeEngine({CEO_Q.text: ([_r("https://a.com", "NVIDIA", "GPU maker")], None)})
    report = await run_answers([CEO_Q], {"bad": bad, "good": good})
    ult = report["engines"]["ultimate"]
    assert ult["recall_at_k"] == 1.0
    assert ult["mrr_at_k"] == 1.0
    pq = ult["per_query"][0]
    assert pq["hit_rank"] == 1
    assert pq["results"][0]["url"] == "https://b.com"
    assert pq["n_results"] == 2


async def test_run_answers_ultimate_scores_zero_when_all_engines_fail():
    err = FakeEngine({CEO_Q.text: (None, {"error_type": "transport", "error_message": "x"})})
    report = await run_answers([CEO_Q], {"e": err})
    ult = report["engines"]["ultimate"]
    assert ult["num_scored"] == 1
    assert ult["search_errors"] == 1
    assert ult["recall_at_k"] == 0.0
