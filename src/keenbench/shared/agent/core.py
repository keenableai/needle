import asyncio
import inspect
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from keenbench.shared.agent.prompts import (
    BUDGET_EXHAUSTED_PROMPT,
    COMPACTION_PROMPT,
    END_PLAN_TOKEN,
    MAX_STEPS_EXCEEDED_PROMPT,
    PLAN_PREFIX,
    PLAN_SUFFIX,
    build_planning_prompt,
)
from keenbench.shared.llm import ChatLLMClient, ChatResult, ChatUsage, LLMClientError

logger = logging.getLogger(__name__)

MAX_TOOL_CONTENT_CHARS = 20_000
DEFAULT_MAX_OUTPUT_TOKENS = 65_535


class AgentError(Exception):
    pass


def truncate_content(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    half = max_chars // 2
    return content[:half] + "\n...[truncated]...\n" + content[-half:]


@dataclass
class Tool:
    name: str
    description: str
    function: Callable[..., Any]
    parameters_schema: dict[str, Any]

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

    @property
    def spent(self) -> float:
        return self.llm_usd + self.tool_usd

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.limit_usd

    def charge_llm(self, usage: ChatUsage) -> None:
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
        llm_client: ChatLLMClient,
        tools: list[Tool],
        system_prompt: str,
        max_steps: int,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        context_window_tokens: int = 200_000,
        compaction_threshold: float = 0.75,
        planning_enabled: bool = False,
        max_tool_content_chars: int = MAX_TOOL_CONTENT_CHARS,
    ) -> None:
        self.llm_client = llm_client
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.max_output_tokens = max_output_tokens
        self.planning_enabled = planning_enabled
        self.max_tool_content_chars = max_tool_content_chars
        self._compaction_token_limit = int(
            (context_window_tokens - max_output_tokens) * compaction_threshold
        )
        self._tool_registry: dict[str, Tool] = {}
        for t in tools:
            if t.name in self._tool_registry:
                raise AgentError(f"Duplicate tool name: {t.name!r}")
            self._tool_registry[t.name] = t
        self._openai_tools = [t.to_openai_schema() for t in tools]

    def _account(self, usage: AgentUsage, response: ChatResult, budget: RunBudget | None) -> None:
        usage.prompt_tokens += response.usage.prompt_tokens
        usage.completion_tokens += response.usage.completion_tokens
        usage.total_tokens += response.usage.prompt_tokens + response.usage.completion_tokens
        usage.llm_calls += 1
        if budget is not None:
            budget.charge_llm(response.usage)

    async def run(self, user_message: str, *, budget: RunBudget | None = None) -> AgentResult:
        usage = AgentUsage()
        records: list[ToolCallRecord] = []
        continuation_chunks: list[str] = []
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message},
        ]
        openai_tools = self._openai_tools or None

        if self.planning_enabled:
            messages.extend(await self._run_planning_step(user_message, usage, budget))

        for step in range(1, self.max_steps + 1):
            if budget is not None and budget.exhausted:
                return await self._finalize(
                    messages,
                    usage,
                    records,
                    budget,
                    prompt=BUDGET_EXHAUSTED_PROMPT,
                    steps=step - 1,
                    finish_reason="budget",
                )
            try:
                response = await self.llm_client.chat(
                    messages, tools=openai_tools, max_tokens=self.max_output_tokens
                )
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
            self._account(usage, response, budget)

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
            executed = await asyncio.gather(
                *(
                    self._execute_tool(
                        tc.get("function", {}).get("name", ""),
                        tc.get("function", {}).get("arguments", "{}"),
                        budget,
                    )
                    for tc in response.tool_calls
                )
            )
            for tc, record in zip(response.tool_calls, executed, strict=True):
                records.append(record)
                content = truncate_content(
                    (record.result if record.error is None else record.error) or "",
                    self.max_tool_content_chars,
                )
                messages.append(
                    {"role": "tool", "tool_call_id": tc.get("id", ""), "content": content}
                )
            if budget is not None:
                messages[-1]["content"] += (
                    f"\n\n[spend so far: ${budget.spent:.3f} of ${budget.limit_usd:.2f}]"
                )

            if response.usage.prompt_tokens > self._compaction_token_limit:
                messages = await self._compact_history(messages, usage, budget)

        return await self._finalize(
            messages,
            usage,
            records,
            budget,
            prompt=MAX_STEPS_EXCEEDED_PROMPT,
            steps=self.max_steps,
            prefix="".join(continuation_chunks),
            max_steps_exceeded=True,
            error_prefix="Max steps exceeded and summarization failed: ",
        )

    async def _finalize(
        self,
        messages: list[dict[str, Any]],
        usage: AgentUsage,
        records: list[ToolCallRecord],
        budget: RunBudget | None,
        *,
        prompt: str,
        steps: int,
        prefix: str = "",
        finish_reason: str | None = None,
        max_steps_exceeded: bool = False,
        error_prefix: str = "",
    ) -> AgentResult:
        try:
            response = await self.llm_client.chat(
                [*messages, {"role": "user", "content": prompt}],
                tools=None,
                max_tokens=self.max_output_tokens,
            )
        except LLMClientError as e:
            return AgentResult(
                content=prefix,
                success=False,
                usage=usage,
                tool_calls=records,
                steps=steps,
                error=f"{error_prefix}{e}",
                finish_reason="error",
                max_steps_exceeded=max_steps_exceeded,
                budget=budget,
            )
        self._account(usage, response, budget)
        return AgentResult(
            content=prefix + (response.content or ""),
            success=True,
            usage=usage,
            tool_calls=records,
            steps=steps,
            finish_reason=finish_reason or response.finish_reason,
            max_steps_exceeded=max_steps_exceeded,
            budget=budget,
        )

    async def _execute_tool(
        self, name: str, raw_arguments: str, budget: RunBudget | None
    ) -> ToolCallRecord:
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
        if budget is not None:
            budget.charge_tool(name)
        try:
            result = tool.function(**arguments)
            if inspect.isawaitable(result):
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
        self, user_message: str, usage: AgentUsage, budget: RunBudget | None
    ) -> list[dict[str, Any]]:
        tool_lines = [f"- {t.name}: {t.description}" for t in self._tool_registry.values()]
        try:
            response = await self.llm_client.chat(
                [{"role": "user", "content": build_planning_prompt(user_message, tool_lines)}],
                tools=None,
                max_tokens=self.max_output_tokens,
            )
            self._account(usage, response, budget)
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
        self, messages: list[dict[str, Any]], usage: AgentUsage, budget: RunBudget | None
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
                max_tokens=self.max_output_tokens,
            )
            self._account(usage, response, budget)
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
