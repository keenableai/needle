import pytest

from keenbench.findall.agent import Agent, RunBudget, Tool
from keenbench.findall.agent.llm_client import LLMResponse, LLMUsage


class ScriptedLLM:
    def __init__(self, responses: list[LLMResponse], model: str = "test/model") -> None:
        self.model = model
        self.max_tokens = 4096
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def chat(self, messages, tools=None, **_):
        self.calls.append({"messages": messages, "tools": tools})
        if not self._responses:
            return LLMResponse(content="{}", usage=LLMUsage(prompt_tokens=1, completion_tokens=1))
        return self._responses.pop(0)


def _tool_call(name: str, args: str, tid: str = "c1") -> dict:
    return {"id": tid, "type": "function", "function": {"name": name, "arguments": args}}


def _search_tool(calls: list[str]) -> Tool:
    async def search(query: str) -> str:
        calls.append(query)
        return f"results for {query}"

    return Tool(
        name="search",
        description="search the web",
        function=search,
        parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
    )


def _budget(limit: float = 1.0) -> RunBudget:
    return RunBudget(
        limit_usd=limit,
        in_price_per_mtok=3.0,
        out_price_per_mtok=15.0,
        tool_cost=lambda _name: 0.01,
    )


async def test_plain_answer_no_tools():
    llm = ScriptedLLM([LLMResponse(content='{"value": 42}', finish_reason="stop")])
    agent = Agent(llm, [], "sys", max_steps=5)
    result = await agent.run("q", budget=_budget())
    assert result.success and result.content == '{"value": 42}'
    assert result.steps == 1


async def test_tool_then_answer_charges_and_records():
    calls: list[str] = []
    llm = ScriptedLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[_tool_call("search", '{"query": "hn launches"}')],
                usage=LLMUsage(prompt_tokens=100, completion_tokens=20),
            ),
            LLMResponse(
                content='{"items": []}', usage=LLMUsage(prompt_tokens=200, completion_tokens=10)
            ),
        ]
    )
    budget = _budget()
    agent = Agent(llm, [_search_tool(calls)], "sys", max_steps=5)
    result = await agent.run("q", budget=budget)
    assert result.success and result.content == '{"items": []}'
    assert calls == ["hn launches"]
    assert budget.tool_calls == {"search": 1}
    assert budget.tool_usd == pytest.approx(0.01)
    assert budget.llm_usd > 0
    assert not budget.exhausted
    assert result.tool_calls[0].result == "results for hn launches"


async def test_budget_exhaustion_forces_final_answer():
    llm = ScriptedLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[_tool_call("search", '{"query": "x"}')],
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
            ),
            LLMResponse(content='{"final": true}'),
        ]
    )
    budget = _budget(limit=0.005)
    agent = Agent(llm, [_search_tool([])], "sys", max_steps=10)
    result = await agent.run("q", budget=budget)
    assert budget.exhausted
    assert result.finish_reason == "budget"
    assert result.content == '{"final": true}'
    assert result.steps == 1


async def test_spend_line_injected_into_tool_result():
    llm = ScriptedLLM(
        [
            LLMResponse(content="", tool_calls=[_tool_call("search", '{"query": "x"}')]),
            LLMResponse(content='{"ok": 1}'),
        ]
    )
    agent = Agent(llm, [_search_tool([])], "sys", max_steps=5)
    await agent.run("q", budget=_budget())
    tool_msg = next(m for m in llm.calls[-1]["messages"] if m.get("role") == "tool")
    assert "[spend so far:" in tool_msg["content"]


async def test_unknown_tool_reports_error_and_continues():
    llm = ScriptedLLM(
        [
            LLMResponse(content="", tool_calls=[_tool_call("missing", "{}")]),
            LLMResponse(content='{"done": 1}'),
        ]
    )
    agent = Agent(llm, [_search_tool([])], "sys", max_steps=5)
    result = await agent.run("q", budget=_budget())
    assert result.success and result.content == '{"done": 1}'
    assert "Unknown tool" in (result.tool_calls[0].error or "")


async def test_max_steps_falls_back_to_summary():
    loop = [
        LLMResponse(content="", tool_calls=[_tool_call("search", '{"query": "x"}')])
        for _ in range(3)
    ]
    llm = ScriptedLLM([*loop, LLMResponse(content='{"best_effort": 1}')])
    agent = Agent(llm, [_search_tool([])], "sys", max_steps=3)
    result = await agent.run("q", budget=_budget())
    assert result.max_steps_exceeded and result.success
    assert result.content == '{"best_effort": 1}'


async def test_planning_step_prepends_plan():
    llm = ScriptedLLM(
        [
            LLMResponse(content="sub-questions: a, b</plan> trailing"),
            LLMResponse(content='{"answer": 1}'),
        ]
    )
    agent = Agent(llm, [_search_tool([])], "sys", max_steps=5, planning_enabled=True)
    result = await agent.run("q", budget=_budget())
    assert result.success and result.content == '{"answer": 1}'
    exec_messages = llm.calls[-1]["messages"]
    plan_msg = exec_messages[2]["content"]
    assert plan_msg.startswith("Here is my plan")
    assert "trailing" not in plan_msg
