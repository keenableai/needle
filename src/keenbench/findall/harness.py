import json
import os
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from keenbench.findall.models import model_price, tool_price

MAX_ERROR_CHARS = 500
TOOL_RESULT_CHARS = 6000
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


class AgentLLM:
    def __init__(self, *, api_key: str, model: str, timeout_s: float = 180.0) -> None:
        self.model = model
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def chat(
        self, messages: list[dict], tools: list[dict]
    ) -> tuple[dict | None, dict[str, int], dict | None]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
        }
        if tools:
            body["tools"] = tools
        try:
            resp = await self._client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=self._headers,
                json=body,
            )
        except httpx.HTTPError as exc:
            return (
                None,
                {},
                {"error_type": "transport", "error_message": str(exc)[:MAX_ERROR_CHARS]},
            )
        if resp.status_code != 200:
            return (
                None,
                {},
                {
                    "error_type": "http_error",
                    "error_message": f"{resp.status_code}: {resp.text[:MAX_ERROR_CHARS]}",
                },
            )
        try:
            payload = resp.json()
            message = payload["choices"][0]["message"]
        except (ValueError, KeyError, IndexError) as exc:
            return None, {}, {"error_type": "bad_json", "error_message": str(exc)[:MAX_ERROR_CHARS]}
        usage = payload.get("usage") or {}
        return (
            message,
            {
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
            },
            None,
        )

    async def aclose(self) -> None:
        await self._client.aclose()


def _mcp_tools_to_openai(tools: list[Any]) -> list[dict]:
    out = []
    for t in tools:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": (t.description or "")[:1024],
                    "parameters": t.inputSchema or {"type": "object", "properties": {}},
                },
            }
        )
    return out


def _tool_result_text(result: Any) -> str:
    parts = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    joined = "\n".join(parts) or "(empty result)"
    if len(joined) > TOOL_RESULT_CHARS:
        joined = joined[:TOOL_RESULT_CHARS] + "\n...[truncated]"
    return joined


async def run_task(
    spec: BackendSpec,
    llm: AgentLLM,
    *,
    prompt: str,
    budget_usd: float,
    max_turns: int = 20,
) -> dict[str, Any]:
    started = time.perf_counter()
    out: dict[str, Any] = {
        "answer_text": None,
        "spent_usd": 0.0,
        "llm_usd": 0.0,
        "tool_usd": 0.0,
        "tool_calls": {},
        "turns": 0,
        "budget_exhausted": False,
        "error": None,
    }
    in_price, out_price = model_price(llm.model)

    def charge_llm(usage: dict[str, int]) -> None:
        cost = (
            usage.get("prompt_tokens", 0) * in_price + usage.get("completion_tokens", 0) * out_price
        ) / 1_000_000
        out["llm_usd"] += cost
        out["spent_usd"] += cost

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
            tools = _mcp_tools_to_openai(listed.tools)

            messages: list[dict] = [
                {"role": "system", "content": SYSTEM_PROMPT.format(budget=budget_usd)},
                {"role": "user", "content": prompt},
            ]
            while out["turns"] < max_turns:
                out["turns"] += 1
                message, usage, err = await llm.chat(messages, tools)
                charge_llm(usage)
                if err is not None or message is None:
                    out["error"] = err or {"error_type": "no_message", "error_message": ""}
                    return out
                messages.append(message)
                tool_calls = message.get("tool_calls") or []
                if not tool_calls:
                    out["answer_text"] = message.get("content") or ""
                    return out
                for call in tool_calls:
                    fn = call.get("function") or {}
                    name = fn.get("name") or ""
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    price = tool_price(name)
                    out["tool_usd"] += price
                    out["spent_usd"] += price
                    out["tool_calls"][name] = out["tool_calls"].get(name, 0) + 1
                    try:
                        result = await session.call_tool(name, args)
                        text = _tool_result_text(result)
                    except Exception as exc:
                        text = f"Tool error: {str(exc)[:MAX_ERROR_CHARS]}"
                    text += f"\n\n[spend so far: ${out['spent_usd']:.3f} of ${budget_usd:.2f}]"
                    messages.append(
                        {"role": "tool", "tool_call_id": call.get("id") or "", "content": text}
                    )
                if out["spent_usd"] >= budget_usd:
                    out["budget_exhausted"] = True
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "The budget is exhausted. Respond now with ONLY the final "
                                "JSON answer to the original task."
                            ),
                        }
                    )
                    message, usage, err = await llm.chat(messages, [])
                    charge_llm(usage)
                    if err is not None or message is None:
                        out["error"] = err or {"error_type": "no_message", "error_message": ""}
                        return out
                    out["answer_text"] = message.get("content") or ""
                    return out
            out["error"] = {"error_type": "max_turns", "error_message": f"{max_turns} turns"}
            return out
    except Exception as exc:
        out["error"] = {"error_type": "backend_crash", "error_message": str(exc)[:MAX_ERROR_CHARS]}
        return out
    finally:
        out["elapsed_s"] = round(time.perf_counter() - started, 1)
