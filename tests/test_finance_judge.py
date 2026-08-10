import json

import pytest

from keenbench.finance import cli as finance_cli
from keenbench.finance.judge import build_answer_prompt, judge_answer, parse_verdict
from keenbench.finance.score import GoldQuery, run_answers
from keenbench.shared import cli as shared_cli
from keenbench.shared.search import SearchResult
from keenbench.shared.search import factory as search_factory

CEO_Q = GoldQuery(
    text="nvidia ceo",
    field="ceo",
    field_type="person",
    value="Jensen Huang",
    aliases=("Jen-Hsun Huang",),
    bucket="finance",
    freshness_window="1y",
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


class FakeJudgeLLM:
    def __init__(self, replies):
        self.replies = replies
        self.prompts = []

    async def complete(self, prompt, *, max_tokens, reasoning_effort):
        self.prompts.append(prompt)
        reply = self.replies[min(len(self.prompts), len(self.replies)) - 1]
        if isinstance(reply, dict):
            return None, reply
        return reply, None

    async def aclose(self):
        pass


def test_parse_verdict():
    assert parse_verdict("yes") is True
    assert parse_verdict(" Yes.") is True
    assert parse_verdict("NO") is False
    assert parse_verdict("no, it does not") is False
    assert parse_verdict("maybe") is None
    assert parse_verdict(None) is None


def test_build_answer_prompt_includes_gold_and_result():
    prompt = build_answer_prompt(
        query_text="nvidia ceo",
        field="ceo",
        value="Jensen Huang",
        aliases=("Jen-Hsun Huang",),
        title="NVIDIA leadership",
        url="https://nvidia.com/leadership",
        snippet="Our founder leads the company.",
    )
    assert "nvidia ceo" in prompt
    assert "Jensen Huang" in prompt
    assert "Jen-Hsun Huang" in prompt
    assert "https://nvidia.com/leadership" in prompt


async def test_judge_answer_verdicts_and_errors():
    llm = FakeJudgeLLM(["yes"])
    verdict, err = await judge_answer(
        llm,
        query_text="q",
        field="ceo",
        value="x",
        aliases=(),
        title=None,
        url="https://a.com",
        snippet="s",
    )
    assert verdict is True and err is None

    llm = FakeJudgeLLM(["gibberish"])
    verdict, err = await judge_answer(
        llm,
        query_text="q",
        field="ceo",
        value="x",
        aliases=(),
        title=None,
        url="https://a.com",
        snippet="s",
    )
    assert verdict is None and err["error_type"] == "judge_parse_error"
    assert len(llm.prompts) == 2


async def test_judge_answer_retries_parse_error():
    llm = FakeJudgeLLM(["gibberish", "no"])
    verdict, err = await judge_answer(
        llm,
        query_text="q",
        field="ceo",
        value="x",
        aliases=(),
        title=None,
        url="https://a.com",
        snippet="s",
    )
    assert verdict is False and err is None
    assert len(llm.prompts) == 2


async def test_judge_upgrades_deterministic_miss():
    engine = FakeEngine(
        {
            CEO_Q.text: (
                [
                    _r("https://a.com", "NVIDIA founder", "the company's longtime leader"),
                    _r("https://b.com", "Leadership", "CEO Jensen Huang"),
                ],
                None,
            )
        }
    )
    llm = FakeJudgeLLM(["yes"])
    report = await run_answers([CEO_Q], {"fake": engine}, judge=llm)
    e = report["engines"]["fake"]
    pq = e["per_query"][0]
    assert pq["det_rank"] == 2
    assert pq["hit_rank"] == 1
    assert pq["judged"] == 1
    assert e["judge_upgrades"] == 1
    assert e["recall_at_k"] == 1.0 and e["mrr_at_k"] == 1.0
    assert len(llm.prompts) == 1
    first, second = pq["results"]
    assert first["det_match"] is False and first["judge_match"] is True
    assert second["det_match"] is True and second["judge_match"] is None
    assert second["snippet"] == "CEO Jensen Huang"


async def test_judge_not_called_at_or_after_deterministic_hit():
    engine = FakeEngine(
        {
            CEO_Q.text: (
                [
                    _r("https://a.com", "Leadership", "CEO Jensen Huang"),
                    _r("https://b.com", "Other", "unrelated"),
                ],
                None,
            )
        }
    )
    llm = FakeJudgeLLM(["yes"])
    report = await run_answers([CEO_Q], {"fake": engine}, judge=llm)
    pq = report["engines"]["fake"]["per_query"][0]
    assert pq["hit_rank"] == 1 and pq["judged"] == 0
    assert llm.prompts == []


async def test_judge_no_keeps_miss():
    engine = FakeEngine({CEO_Q.text: ([_r("https://a.com", "NVIDIA", "GPU maker")], None)})
    report = await run_answers([CEO_Q], {"fake": engine}, judge=FakeJudgeLLM(["no"]))
    e = report["engines"]["fake"]
    assert e["recall_at_k"] == 0.0 and e["num_scored"] == 1 and e["judge_upgrades"] == 0


async def test_judge_error_excludes_unresolved_miss():
    engine = FakeEngine({CEO_Q.text: ([_r("https://a.com", "NVIDIA", "GPU maker")], None)})
    err = {"error_type": "http_error", "error_message": "429"}
    report = await run_answers([CEO_Q], {"fake": engine}, judge=FakeJudgeLLM([err]))
    e = report["engines"]["fake"]
    assert e["num_scored"] == 0 and e["judge_errors"] == 1
    assert e["by_field"] == {}


async def test_ultimate_uses_queries_scored_by_any_engine():
    clean = FakeEngine({CEO_Q.text: ([_r("https://a.com", "NVIDIA", "GPU maker")], None)})
    failed = FakeEngine({CEO_Q.text: ([_r("https://b.com", "NVIDIA", "GPU maker")], None)})
    err = {"error_type": "http_error", "error_message": "429"}
    report = await run_answers(
        [CEO_Q], {"clean": clean, "failed": failed}, judge=FakeJudgeLLM(["no", err])
    )
    assert report["engines"]["clean"]["num_scored"] == 1
    assert report["engines"]["failed"]["num_scored"] == 0
    ultimate = report["engines"]["ultimate"]
    assert ultimate["num_scored"] == 1
    assert ultimate["judge_errors"] == 0
    assert ultimate["per_query"][0]["n_results"] == 1
    assert ultimate["per_query"][0]["results"][0]["url"] == "https://a.com"


def test_run_judge_requires_openrouter_key(tmp_path, monkeypatch):
    f = tmp_path / "q.jsonl"
    row = {
        "query_text": "nvidia ceo",
        "query_origin": json.dumps({"bucket": "finance"}),
        "gold": {"field": "ceo", "field_type": "person", "value": "Jensen Huang", "aliases": []},
    }
    f.write_text(json.dumps(row) + "\n")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        finance_cli.Finance().run(queries=str(f), engines="keenable", judge=True)


def test_run_passes_judge_model(tmp_path, monkeypatch):
    f = tmp_path / "q.jsonl"
    row = {
        "query_text": "nvidia ceo",
        "query_origin": json.dumps({"bucket": "finance"}),
        "gold": {"field": "ceo", "field_type": "person", "value": "Jensen Huang", "aliases": []},
    }
    f.write_text(json.dumps(row) + "\n")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")

    created = {}

    class FakeOpenRouter:
        def __init__(self, **kwargs):
            created.update(kwargs)

        async def aclose(self):
            pass

    class FakeKeenable:
        def __init__(self, **kwargs):
            pass

        async def aclose(self):
            pass

    seen = {}

    async def fake_run_answers(queries, clients, **kwargs):
        seen["judge"] = kwargs.get("judge")
        return {"num_queries": 1, "num_results": 5, "snippet_chars": 500, "engines": {}}

    monkeypatch.setattr(shared_cli, "OpenRouterClient", FakeOpenRouter)
    monkeypatch.setattr(search_factory, "KeenableClient", FakeKeenable)
    monkeypatch.setattr(finance_cli, "run_answers", fake_run_answers)
    out = tmp_path / "r.json"
    finance_cli.Finance().run(
        queries=str(f), engines="keenable", judge=True, judge_model="test/model", out=str(out)
    )
    assert created == {"api_key": "or-key", "model": "test/model", "timeout_s": 60.0}
    assert seen["judge"] is not None
    assert json.loads(out.read_text())["judge_model"] == "test/model"
