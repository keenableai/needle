import pytest
from mcp.types import CallToolResult, TextContent

from keenbench.shared.agent import Agent, RunBudget, Tool
from keenbench.shared.agent.core import truncate_content
from keenbench.shared.agent.mcp import _dispatch
from keenbench.shared.llm import ChatResult, ChatUsage


class ScriptedLLM:
    def __init__(self, responses: list[ChatResult]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def chat(self, messages, tools=None, **_):
        self.calls.append({"messages": messages, "tools": tools})
        if not self._responses:
            return ChatResult(content="{}", usage=ChatUsage(prompt_tokens=1, completion_tokens=1))
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
    llm = ScriptedLLM([ChatResult(content='{"value": 42}', finish_reason="stop")])
    agent = Agent(llm, [], "sys", max_steps=5)
    result = await agent.run("q", budget=_budget())
    assert result.success and result.content == '{"value": 42}'
    assert result.steps == 1


async def test_tool_then_answer_charges_and_records():
    calls: list[str] = []
    llm = ScriptedLLM(
        [
            ChatResult(
                content="",
                tool_calls=[_tool_call("search", '{"query": "hn launches"}')],
                usage=ChatUsage(prompt_tokens=100, completion_tokens=20),
            ),
            ChatResult(
                content='{"items": []}', usage=ChatUsage(prompt_tokens=200, completion_tokens=10)
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
            ChatResult(
                content="",
                tool_calls=[_tool_call("search", '{"query": "x"}')],
                usage=ChatUsage(prompt_tokens=10, completion_tokens=5),
            ),
            ChatResult(content='{"final": true}'),
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
            ChatResult(content="", tool_calls=[_tool_call("search", '{"query": "x"}')]),
            ChatResult(content='{"ok": 1}'),
        ]
    )
    agent = Agent(llm, [_search_tool([])], "sys", max_steps=5)
    await agent.run("q", budget=_budget())
    tool_msg = next(m for m in llm.calls[-1]["messages"] if m.get("role") == "tool")
    assert "[spend so far:" in tool_msg["content"]


async def test_unknown_tool_reports_error_and_is_not_charged():
    llm = ScriptedLLM(
        [
            ChatResult(content="", tool_calls=[_tool_call("missing", "{}")]),
            ChatResult(content='{"done": 1}'),
        ]
    )
    budget = _budget()
    agent = Agent(llm, [_search_tool([])], "sys", max_steps=5)
    result = await agent.run("q", budget=budget)
    assert result.success and result.content == '{"done": 1}'
    assert "Unknown tool" in (result.tool_calls[0].error or "")
    assert budget.tool_calls == {}
    assert budget.tool_usd == 0.0


async def test_max_steps_falls_back_to_summary():
    loop = [
        ChatResult(content="", tool_calls=[_tool_call("search", '{"query": "x"}')])
        for _ in range(3)
    ]
    llm = ScriptedLLM([*loop, ChatResult(content='{"best_effort": 1}')])
    agent = Agent(llm, [_search_tool([])], "sys", max_steps=3)
    result = await agent.run("q", budget=_budget())
    assert result.max_steps_exceeded and result.success
    assert result.content == '{"best_effort": 1}'


async def test_planning_step_prepends_plan():
    llm = ScriptedLLM(
        [
            ChatResult(content="sub-questions: a, b</plan> trailing"),
            ChatResult(content='{"answer": 1}'),
        ]
    )
    agent = Agent(llm, [_search_tool([])], "sys", max_steps=5, planning_enabled=True)
    result = await agent.run("q", budget=_budget())
    assert result.success and result.content == '{"answer": 1}'
    exec_messages = llm.calls[-1]["messages"]
    plan_msg = exec_messages[2]["content"]
    assert plan_msg.startswith("Here is my plan")
    assert "trailing" not in plan_msg


async def test_llm_only_spend_exhausts_budget():
    llm = ScriptedLLM(
        [
            ChatResult(
                content="part ",
                finish_reason="length",
                usage=ChatUsage(prompt_tokens=1_000_000, completion_tokens=10),
            ),
            ChatResult(content='{"final": 1}'),
        ]
    )
    budget = _budget(limit=1.0)
    agent = Agent(llm, [], "sys", max_steps=5)
    result = await agent.run("q", budget=budget)
    assert budget.exhausted
    assert result.finish_reason == "budget"
    assert result.content == '{"final": 1}'
    assert result.steps == 1


async def test_spend_line_once_per_turn():
    llm = ScriptedLLM(
        [
            ChatResult(
                content="",
                tool_calls=[
                    _tool_call("search", '{"query": "a"}', "c1"),
                    _tool_call("search", '{"query": "b"}', "c2"),
                ],
            ),
            ChatResult(content='{"ok": 1}'),
        ]
    )
    agent = Agent(llm, [_search_tool([])], "sys", max_steps=5)
    await agent.run("q", budget=_budget())
    tool_msgs = [m for m in llm.calls[-1]["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) == 2
    assert "[spend so far:" not in tool_msgs[0]["content"]
    assert "[spend so far:" in tool_msgs[1]["content"]


async def test_sync_tool_result_is_awaited_correctly():
    def add(a: int, b: int) -> int:
        return a + b

    tool = Tool(
        name="add",
        description="add two numbers",
        function=add,
        parameters_schema={
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        },
    )
    llm = ScriptedLLM(
        [
            ChatResult(content="", tool_calls=[_tool_call("add", '{"a": 2, "b": 3}')]),
            ChatResult(content='{"sum": 5}'),
        ]
    )
    agent = Agent(llm, [tool], "sys", max_steps=5)
    result = await agent.run("q")
    assert result.tool_calls[0].error is None
    assert result.tool_calls[0].result == "5"


def test_truncate_content_keeps_head_and_tail():
    text = "a" * 50 + "b" * 50
    out = truncate_content(text, 20)
    assert out.startswith("a" * 10)
    assert out.endswith("b" * 10)
    assert "...[truncated]..." in out


async def test_mcp_dispatch_raises_on_error_result():
    class FakeSession:
        async def call_tool(self, name, kwargs, read_timeout_seconds=None):
            return CallToolResult(content=[TextContent(type="text", text="boom")], isError=True)

    call = _dispatch(FakeSession(), "t")
    with pytest.raises(RuntimeError, match="boom"):
        await call()
