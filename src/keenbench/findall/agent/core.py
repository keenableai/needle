import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from keenbench.findall.agent.llm_client import LLMClient, LLMClientError, LLMResponse, LLMUsage
from keenbench.findall.agent.prompts import (
    COMPACTION_PROMPT,
    END_PLAN_TOKEN,
    MAX_STEPS_EXCEEDED_PROMPT,
    PLAN_PREFIX,
    PLAN_SUFFIX,
    build_planning_prompt,
)

logger = logging.getLogger(__name__)

MAX_TOOL_CONTENT_CHARS = 6000
BUDGET_EXHAUSTED_PROMPT = (
    "The budget is exhausted. Respond now with ONLY the final JSON answer to the original task."
)


class AgentError(Exception):
    pass


def truncate_content(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "\n...[truncated]"


@dataclass
class Tool:
    name: str
    description: str
    function: Callable[..., Any]
    parameters_schema: dict[str, Any]
    is_async: bool = True

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    result: str | None = None
    error: str | None = None


@dataclass
class AgentUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    llm_calls: int = 0
    compactions: int = 0


@dataclass
class RunBudget:
    limit_usd: float
    in_price_per_mtok: float
    out_price_per_mtok: float
    tool_cost: Callable[[str], float]
    llm_usd: float = 0.0
    tool_usd: float = 0.0
    tool_calls: dict[str, int] = field(default_factory=dict)
    exhausted: bool = False

    @property
    def spent(self) -> float:
        return self.llm_usd + self.tool_usd

    def charge_llm(self, usage: LLMUsage) -> None:
        self.llm_usd += (
            usage.prompt_tokens * self.in_price_per_mtok
            + usage.completion_tokens * self.out_price_per_mtok
        ) / 1_000_000

    def charge_tool(self, name: str) -> None:
        self.tool_usd += self.tool_cost(name)
        self.tool_calls[name] = self.tool_calls.get(name, 0) + 1


@dataclass
class AgentResult:
    content: str
    success: bool
    usage: AgentUsage = field(default_factory=AgentUsage)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    steps: int = 0
    error: str | None = None
    finish_reason: str = "stop"
    max_steps_exceeded: bool = False
    budget: RunBudget | None = None


class Agent:
    def __init__(
        self,
        llm_client: LLMClient,
        tools: list[Tool],
        system_prompt: str,
        max_steps: int,
        context_window_tokens: int = 200_000,
        compaction_threshold: float = 0.75,
        planning_enabled: bool = False,
        max_tool_content_chars: int = MAX_TOOL_CONTENT_CHARS,
    ) -> None:
        self.llm_client = llm_client
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.planning_enabled = planning_enabled
        self.max_tool_content_chars = max_tool_content_chars
        self._compaction_token_limit = int(
            (context_window_tokens - llm_client.max_tokens) * compaction_threshold
        )
        self._tool_registry: dict[str, Tool] = {}
        for t in tools:
            if t.name in self._tool_registry:
                raise AgentError(f"Duplicate tool name: {t.name!r}")
            self._tool_registry[t.name] = t
        self._openai_tools = [t.to_openai_schema() for t in tools]
        self._budget: RunBudget | None = None

    @property
    def openai_tools(self) -> list[dict[str, Any]]:
        return self._openai_tools

    def _account(self, usage: AgentUsage, response: LLMResponse) -> None:
        usage.prompt_tokens += response.usage.prompt_tokens
        usage.completion_tokens += response.usage.completion_tokens
        usage.total_tokens += response.usage.total_tokens
        usage.llm_calls += 1
        if self._budget is not None:
            self._budget.charge_llm(response.usage)

    async def run(self, user_message: str, *, budget: RunBudget | None = None) -> AgentResult:
        self._budget = budget
        usage = AgentUsage()
        records: list[ToolCallRecord] = []
        continuation_chunks: list[str] = []
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message},
        ]
        openai_tools = self._openai_tools or None

        if self.planning_enabled:
            messages.extend(await self._run_planning_step(user_message, usage))

        for step in range(1, self.max_steps + 1):
            try:
                response = await self.llm_client.chat(messages, tools=openai_tools)
            except LLMClientError as e:
                return AgentResult(
                    content="".join(continuation_chunks),
                    success=False,
                    usage=usage,
                    tool_calls=records,
                    steps=step,
                    error=str(e),
                    finish_reason="error",
                    budget=budget,
                )
            self._account(usage, response)

            if not response.tool_calls:
                messages.append({"role": "assistant", "content": response.content})
                if response.finish_reason == "length":
                    continuation_chunks.append(response.content)
                    messages.append({"role": "user", "content": "Continue."})
                    continue
                full = (
                    "".join(continuation_chunks) + response.content
                    if continuation_chunks
                    else response.content
                )
                return AgentResult(
                    content=full,
                    success=True,
                    usage=usage,
                    tool_calls=records,
                    steps=step,
                    finish_reason=response.finish_reason,
                    budget=budget,
                )
            continuation_chunks.clear()

            messages.append(
                {
                    "role": "assistant",
                    "content": response.content or None,
                    "tool_calls": response.tool_calls,
                }
            )
            parsed = [
                (tc.get("id", ""), tc.get("function", {}).get("name", ""), tc.get("function", {}))
                for tc in response.tool_calls
            ]
            executed = await asyncio.gather(
                *(
                    self._execute_tool(fn.get("name", ""), fn.get("arguments", "{}"))
                    for _, _, fn in parsed
                )
            )
            for (tc_id, name, _), record in zip(parsed, executed, strict=True):
                records.append(record)
                if budget is not None:
                    budget.charge_tool(name)
                content = truncate_content(
                    (record.result if record.error is None else record.error) or "",
                    self.max_tool_content_chars,
                )
                if budget is not None:
                    content += f"\n\n[spend so far: ${budget.spent:.3f} of ${budget.limit_usd:.2f}]"
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": content})

            if budget is not None and budget.spent >= budget.limit_usd:
                budget.exhausted = True
                messages.append({"role": "user", "content": BUDGET_EXHAUSTED_PROMPT})
                try:
                    final = await self.llm_client.chat(messages, tools=None)
                except LLMClientError as e:
                    return AgentResult(
                        content="",
                        success=False,
                        usage=usage,
                        tool_calls=records,
                        steps=step,
                        error=str(e),
                        finish_reason="error",
                        budget=budget,
                    )
                self._account(usage, final)
                return AgentResult(
                    content=final.content or "",
                    success=True,
                    usage=usage,
                    tool_calls=records,
                    steps=step,
                    finish_reason="budget",
                    budget=budget,
                )

            if response.usage.prompt_tokens > self._compaction_token_limit:
                messages = await self._compact_history(messages, usage)

        return await self._handle_max_steps_exceeded(messages, usage, records, continuation_chunks)

    async def _execute_tool(self, name: str, raw_arguments: str) -> ToolCallRecord:
        try:
            arguments = json.loads(raw_arguments) if raw_arguments else {}
        except json.JSONDecodeError as e:
            return ToolCallRecord(
                name=name, arguments={}, error=f"Failed to parse tool arguments: {e}"
            )
        tool = self._tool_registry.get(name)
        if tool is None:
            available = ", ".join(sorted(self._tool_registry))
            return ToolCallRecord(
                name=name,
                arguments=arguments,
                error=f"Unknown tool {name!r}. Available tools: {available}",
            )
        try:
            result = tool.function(**arguments)
            if tool.is_async:
                result = await result
            return ToolCallRecord(name=name, arguments=arguments, result=str(result))
        except Exception as e:
            logger.warning("Tool %r raised: %s", name, e)
            return ToolCallRecord(
                name=name,
                arguments=arguments,
                error=f"Tool execution error: {type(e).__name__}: {e}",
            )

    async def _run_planning_step(
        self, user_message: str, usage: AgentUsage
    ) -> list[dict[str, Any]]:
        tool_lines = [f"- {t.name}: {t.description}" for t in self._tool_registry.values()]
        try:
            response = await self.llm_client.chat(
                [{"role": "user", "content": build_planning_prompt(user_message, tool_lines)}],
                tools=None,
            )
            self._account(usage, response)
        except LLMClientError as e:
            logger.warning("Planning step failed, skipping: %s", e)
            return []
        output = PLAN_PREFIX + (response.content or "")
        if END_PLAN_TOKEN in output:
            output = output.split(END_PLAN_TOKEN)[0].strip()
        output += "\n" + END_PLAN_TOKEN
        return [
            {"role": "assistant", "content": output},
            {"role": "user", "content": PLAN_SUFFIX},
        ]

    async def _compact_history(
        self, messages: list[dict[str, Any]], usage: AgentUsage
    ) -> list[dict[str, Any]]:
        tail_start = len(messages)
        for i in range(len(messages) - 1, 1, -1):
            if messages[i].get("role") == "assistant" and messages[i].get("tool_calls"):
                tail_start = i
                break
        compactable = messages[2:tail_start]
        if not compactable:
            return messages
        serialized = json.dumps(compactable, default=str)
        try:
            response = await self.llm_client.chat(
                [
                    {"role": "system", "content": COMPACTION_PROMPT},
                    {"role": "user", "content": serialized},
                ],
                tools=None,
            )
            self._account(usage, response)
            summary = response.content
        except LLMClientError:
            logger.warning("Compaction failed, falling back to truncation")
            summary = truncate_content(serialized, 10_000)
        usage.compactions += 1
        return [
            *messages[:2],
            {"role": "user", "content": f"[Conversation history summary]\n{summary}"},
            *messages[tail_start:],
        ]

    async def _handle_max_steps_exceeded(
        self,
        messages: list[dict[str, Any]],
        usage: AgentUsage,
        records: list[ToolCallRecord],
        continuation_chunks: list[str],
    ) -> AgentResult:
        prefix = "".join(continuation_chunks)
        try:
            response = await self.llm_client.chat(
                [*messages, {"role": "user", "content": MAX_STEPS_EXCEEDED_PROMPT}], tools=None
            )
            self._account(usage, response)
            return AgentResult(
                content=prefix + response.content,
                success=True,
                usage=usage,
                tool_calls=records,
                steps=self.max_steps,
                finish_reason=response.finish_reason,
                max_steps_exceeded=True,
                budget=self._budget,
            )
        except LLMClientError as e:
            return AgentResult(
                content=prefix,
                success=False,
                usage=usage,
                tool_calls=records,
                steps=self.max_steps,
                error=f"Max steps exceeded and summarization failed: {e}",
                finish_reason="error",
                max_steps_exceeded=True,
                budget=self._budget,
            )
