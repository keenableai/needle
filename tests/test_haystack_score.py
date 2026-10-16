import pytest

from needle.finance.score import GoldQuery
from needle.haystack import cli as haystack_cli
from needle.haystack.score import depth_bucket, run_haystack
from needle.shared.search import SearchResult


def _q(text, value, field_type="entity", bucket="gov", syntax="plain", depth=62, cues=()):
    return GoldQuery(
        text=text,
        field=field_type,
        field_type=field_type,
        value=value,
        aliases=(),
        bucket=bucket,
        freshness_window="static",
        syntax=syntax,
        cues=cues,
        extras=(("depth_pct", depth),),
    )


GOV_Q = _q("which instrument charted the acme deep floor", "keelhauler sonar array")
WIKI_Q = _q(
    "what year did the acme expedition first sail",
    "1987",
    field_type="year",
    bucket="wiki",
    syntax="site",
    depth=88,
    cues=("sailed",),
)


def _r(url, title=None, snippet=None):
    return SearchResult(url=url, title=title, snippet=snippet)


class FakeEngine:
    def __init__(self, canned):
        self.canned = canned
        self.latencies_ms = []

    async def search(self, query, *, num_results=10):
        return self.canned.get(query, ([], None))

    async def aclose(self):
        pass


class FakeJudge:
    def __init__(self, verdict="yes"):
        self.verdict = verdict
        self.prompts = []

    async def complete(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return self.verdict, None


def test_depth_bucket_bounds():
    assert depth_bucket(55) == "55-70"
    assert depth_bucket(69) == "55-70"
    assert depth_bucket(70) == "70-85"
    assert depth_bucket(85) == "85-100"
    assert depth_bucket(100) == "85-100"


async def test_run_haystack_metrics_and_breakdowns():
    engine = FakeEngine(
        {
            GOV_Q.text: (
                [
                    _r("https://a.com", "Acme expedition", "an overview of the voyage"),
                    _r("https://b.com", "Instruments", "the keelhauler sonar array charted it"),
                ],
                None,
            ),
            WIKI_Q.text: (
                [
                    _r("https://x.com", "Timeline", "the 1987 harvest festival program"),
                    _r("https://c.com", "History", "it first sailed in 1987"),
                ],
                None,
            ),
        }
    )
    report = await run_haystack([GOV_Q, WIKI_Q], {"fake": engine}, num_results=5)
    e = report["engines"]["fake"]
    assert e["recall_at_k"] == 1.0
    assert e["per_query"][1]["hit_rank"] == 2
    assert e["per_query"][1]["results"][0]["det_match"] is False
    assert e["mrr_at_k"] == pytest.approx((1 / 2 + 1 / 2) / 2)
    assert e["by_bucket"]["gov"] == {"n": 1, "recall_at_k": 1.0}
    assert e["by_syntax"]["site"]["n"] == 1
    assert e["by_field_type"] == {
        "entity": {"n": 1, "recall_at_k": 1.0},
        "year": {"n": 1, "recall_at_k": 1.0},
    }
    assert e["by_depth"] == {
        "55-70": {"n": 1, "recall_at_k": 1.0},
        "85-100": {"n": 1, "recall_at_k": 1.0},
    }
    assert "by_field" not in e
    pq = e["per_query"][0]
    assert pq["depth_pct"] == 62
    assert pq["results"][1]["det_match"] is True
    ult = report["engines"]["ultimate"]
    assert ult["per_query"][0]["hit_rank"] == 1
    assert ult["per_query"][0]["depth_pct"] == 62


async def test_judge_upgrades_use_haystack_prompt():
    engine = FakeEngine(
        {
            GOV_Q.text: (
                [
                    _r("https://a.com", "Instruments", "the array that charted the deep floor"),
                    _r("https://b.com", "Specs", "built as the keelhauler sonar array"),
                ],
                None,
            ),
        }
    )
    judge = FakeJudge("yes")
    report = await run_haystack([GOV_Q], {"fake": engine}, num_results=5, judge=judge)
    e = report["engines"]["fake"]
    assert e["per_query"][0]["det_rank"] == 2
    assert e["per_query"][0]["hit_rank"] == 1
    assert e["judge_upgrades"] == 1
    assert len(judge.prompts) == 1
    assert "fact-lookup benchmark" in judge.prompts[0]
    assert "deep inside a long source document" in judge.prompts[0]


async def test_judge_no_keeps_deterministic_rank():
    engine = FakeEngine(
        {
            GOV_Q.text: (
                [
                    _r("https://a.com", "Overview", "nothing relevant"),
                    _r("https://b.com", "Specs", "the keelhauler sonar array"),
                ],
                None,
            ),
        }
    )
    report = await run_haystack([GOV_Q], {"fake": engine}, num_results=5, judge=FakeJudge("no"))
    e = report["engines"]["fake"]
    assert e["per_query"][0]["hit_rank"] == 2
    assert e["judge_upgrades"] == 0


async def test_judge_error_excludes_unresolved_miss():
    class ErrJudge:
        async def complete(self, prompt, **kwargs):
            return None, {"error_type": "http_error", "error_message": "500"}

    engine = FakeEngine({GOV_Q.text: ([_r("https://a.com", "Overview", "nothing")], None)})
    report = await run_haystack([GOV_Q], {"fake": engine}, num_results=5, judge=ErrJudge())
    e = report["engines"]["fake"]
    assert e["num_scored"] == 0
    assert e["by_bucket"] == {}


async def test_year_without_cue_in_snippet_is_a_miss():
    engine = FakeEngine(
        {
            WIKI_Q.text: (
                [_r("https://a.com", "Almanac", "notable events of 1987 listed here")],
                None,
            )
        }
    )
    report = await run_haystack([WIKI_Q], {"fake": engine}, num_results=5)
    assert report["engines"]["fake"]["per_query"][0]["hit_rank"] is None


def test_gold_ok_and_gold_query_roundtrip():
    row = {
        "query_text": "which instrument charted the acme deep floor site:federalregister.gov",
        "query_origin": {
            "bucket": "gov",
            "syntax": "site",
            "provenance": {"depth_pct": 73, "source_url": "https://x"},
        },
        "gold": {
            "field": "haystack",
            "field_type": "entity",
            "value": "keelhauler sonar array",
            "cues": [
                "charted",
            ],
            "aliases": [],
            "freshness_window": "static",
            "tier": "",
        },
    }
    assert haystack_cli._gold_ok(row["gold"]) is True
    q = haystack_cli._gold_query(row)
    assert q.field == "entity"
    assert q.bucket == "gov"
    assert q.syntax == "site"
    assert dict(q.extras)["depth_pct"] == 73
    assert q.cues == ()

    year_gold = {"field_type": "year", "value": "1987", "cues": ["sailed"]}
    assert haystack_cli._gold_ok(year_gold) is True
    assert haystack_cli._gold_ok({"field_type": "year", "value": "1987"}) is False
    yq = haystack_cli._gold_query({"query_text": "q", "query_origin": {}, "gold": year_gold})
    assert yq.cues == ("sailed",)

    assert haystack_cli._gold_ok({"field_type": "entity", "value": ""}) is False
    assert haystack_cli._gold_ok({"value": "x"}) is False
    with pytest.raises(SystemExit):
        haystack_cli._gold_ok({"field_type": "country", "value": "France"})
