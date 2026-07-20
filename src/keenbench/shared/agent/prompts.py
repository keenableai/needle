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

BUDGET_EXHAUSTED_PROMPT = (
    "The budget is exhausted. Respond now with only your final answer to the original task."
)

NUDGE_PROMPT_TEMPLATE = (
    "You have spent only ${spent:.2f} of your ${limit:.2f} budget - do not finalize yet. "
    "A single probe returning zero or few results is a failed probe, not an answer. Use "
    "the remaining budget to gather more evidence or verify your answer against an "
    "independent source, then give your final answer."
)

WRAP_UP_PROMPT = (
    "The budget is exhausted. Do not run any new searches or fetch new pages. You may "
    "use a few more tool calls ONLY to consolidate evidence you already gathered (for "
    "example, aggregate or re-read saved result sets), then respond with only your final "
    "answer to the original task. Never drop an entity you found: an imperfect real item "
    "can still score, an omitted one cannot."
)

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
