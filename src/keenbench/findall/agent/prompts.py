from datetime import UTC, datetime

END_PLAN_TOKEN = "</plan>"

COMPACTION_PROMPT = """Summarize the following conversation history. Use this exact format:

## Queries tried
- <each unique search query, one per line>

## URLs seen
- <each unique URL from search results or fetches, one per line>

## Key findings
<what was learned, promising leads, dead ends, errors>

## Current hypothesis
<best answer so far and remaining gaps>

Be exhaustive in the Queries and URLs sections — the assistant must not repeat searches or re-visit pages already seen."""

MAX_STEPS_EXCEEDED_PROMPT = (
    "You have used all available steps. Based on the conversation and tool results so "
    "far, provide your best answer to the user's original question. Synthesize what "
    "you've learned."
)

PLANNING_PROMPT_TEMPLATE = """Here is the task:
{task}

Here are the tools available:
{tools}

Current date: {current_date}

Break the task into independent sub-questions that can be researched separately, consider search strategies for them.
Identify which sub-questions are most searchable and should be tackled first.
Note any constraints that could eliminate candidate answers early.
Consider what types of sources are most likely to contain the answer.
If the question has multiple possible interpretations, list them.

Write a plan that:
- Addresses each sub-question
- Prioritizes the most promising entry points
- Includes verification steps to check the final answer against all original constraints
- Uses available tools
- Starts with <plan> tag and ends with </plan> tag

Be concise. One line per sub-question, one line per strategy. No preamble or explanation outside the plan tags."""

PLAN_PREFIX = "Here is my plan to solve the task:\n\n"

PLAN_SUFFIX = (
    "Execute the plan using the available tools. Adapt based on what you find. Before "
    "answering, verify your conclusion against every constraint in the original question."
)


def build_planning_prompt(task: str, tool_lines: list[str]) -> str:
    return PLANNING_PROMPT_TEMPLATE.format(
        task=task,
        tools="\n".join(tool_lines),
        current_date=datetime.now(UTC).strftime("%Y-%m-%d"),
    )
