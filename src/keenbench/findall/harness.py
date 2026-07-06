import asyncio
import os
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from keenbench.findall.models import model_price, tool_price
from keenbench.shared.agent import Agent, RunBudget, mcp_tools_from_session
from keenbench.shared.llm import OpenRouterClient

MAX_ERROR_CHARS = 500
SYSTEM_PROMPT = (
    "You are a research agent with access to web-search tools. Answer the user's "
    "question using evidence gathered with the tools, not your prior knowledge alone.\n"
    "You operate under a hard budget of ${budget:.2f}: every LLM turn and every tool "
    "call costs money, and the running spend is shown after each tool result. Plan "
    "your tool use to extract the most evidence per dollar. Before the budget runs "
    "out, stop calling tools and give your final answer.\n"
    "Your final message must be ONLY the JSON object the task asks for - no prose, "
    "no markdown fences."
)


@dataclass(frozen=True)
class BackendSpec:
    name: str
    kind: str
    command: tuple[str, ...] = ()
    url: str = ""
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)


def resolve_backend(name: str) -> BackendSpec:
    if name == "keenable":
        cmd = os.environ.get("KEENBENCH_KEENABLE_MCP_CMD") or "npx -y @keenable/mcp-server"
        env = {}
        if os.environ.get("KEENABLE_API_KEY"):
            env["KEENABLE_API_KEY"] = os.environ["KEENABLE_API_KEY"]
        return BackendSpec(name=name, kind="stdio", command=tuple(cmd.split()), env=env)
    if name == "webql":
        url = os.environ.get("KEENBENCH_WEBQL_MCP_URL")
        if not url:
            token = os.environ.get("KEENABLE_API_KEY")
            if not token:
                raise ValueError(
                    "backend 'webql' needs KEENBENCH_WEBQL_MCP_URL or KEENABLE_API_KEY"
                )
            url = f"https://webql.keenable.ai/mcp?token={token}"
        return BackendSpec(name=name, kind="http", url=url)
    if name == "exa":
        url = os.environ.get("KEENBENCH_EXA_MCP_URL")
        if not url:
            key = os.environ.get("EXA_API_KEY")
            if not key:
                raise ValueError("backend 'exa' needs KEENBENCH_EXA_MCP_URL or EXA_API_KEY")
            url = f"https://mcp.exa.ai/mcp?exaApiKey={key}"
        return BackendSpec(name=name, kind="http", url=url)
    if name == "parallel":
        url = os.environ.get("KEENBENCH_PARALLEL_MCP_URL") or "https://search.parallel.ai/mcp"
        headers = {}
        if os.environ.get("PARALLEL_API_KEY"):
            headers["x-api-key"] = os.environ["PARALLEL_API_KEY"]
        return BackendSpec(name=name, kind="http", url=url, headers=headers)
    raise ValueError(f"unknown backend {name!r} (known: keenable, webql, exa, parallel)")


async def run_task(
    spec: BackendSpec,
    llm: OpenRouterClient,
    *,
    prompt: str,
    budget_usd: float,
    max_turns: int = 20,
    deadline_s: float = 900.0,
) -> dict[str, Any]:
    started = time.perf_counter()
    in_price, out_price = model_price(llm.model)
    budget = RunBudget(
        limit_usd=budget_usd,
        in_price_per_mtok=in_price,
        out_price_per_mtok=out_price,
        tool_cost=tool_price,
    )
    out: dict[str, Any] = {"answer_text": None, "turns": 0, "error": None}
    try:
        await asyncio.wait_for(
            _run_task_inner(spec, llm, out, budget, prompt=prompt, max_turns=max_turns),
            timeout=deadline_s,
        )
    except TimeoutError:
        out["error"] = {
            "error_type": "cell_timeout",
            "error_message": f"exceeded {deadline_s:.0f}s wall clock",
        }
    out["spent_usd"] = budget.spent
    out["llm_usd"] = budget.llm_usd
    out["tool_usd"] = budget.tool_usd
    out["tool_calls"] = budget.tool_calls
    out["budget_exhausted"] = budget.exhausted
    out["elapsed_s"] = round(time.perf_counter() - started, 1)
    return out


async def _run_task_inner(
    spec: BackendSpec,
    llm: OpenRouterClient,
    out: dict[str, Any],
    budget: RunBudget,
    *,
    prompt: str,
    max_turns: int,
) -> None:
    try:
        async with AsyncExitStack() as stack:
            if spec.kind == "stdio":
                params = StdioServerParameters(
                    command=spec.command[0],
                    args=list(spec.command[1:]),
                    env={**os.environ, **spec.env},
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            else:
                read, write, _ = await stack.enter_async_context(
                    streamablehttp_client(spec.url, headers=spec.headers or None)
                )
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            listed = await session.list_tools()
            agent = Agent(
                llm,
                mcp_tools_from_session(session, listed.tools),
                SYSTEM_PROMPT.format(budget=budget.limit_usd),
                max_steps=max_turns,
            )
            result = await agent.run(prompt, budget=budget)
            out["turns"] = result.steps
            if result.error is not None:
                out["error"] = {
                    "error_type": "agent_error",
                    "error_message": result.error[:MAX_ERROR_CHARS],
                }
            else:
                out["answer_text"] = result.content
    except Exception as exc:
        out["error"] = {"error_type": "backend_crash", "error_message": str(exc)[:MAX_ERROR_CHARS]}
