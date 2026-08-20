from typing import Any

from needle.shared.judge import complete_parsed
from needle.shared.llm import LLMClient
from needle.shared.prompts import render_prompt

ANSWER_TEMPLATE = "answer_match.jinja"
VERDICT_RETRY_SUFFIX = (
    "\n\nYour previous reply could not be parsed. Answer with a single word: yes or no."
)


def build_answer_prompt(
    *,
    query_text: str,
    field: str,
    value: Any,
    aliases: tuple[str, ...],
    title: str | None,
    url: str,
    snippet: str,
) -> str:
    return render_prompt(
        "needle.finance",
        ANSWER_TEMPLATE,
        query=query_text,
        field=field,
        value=value,
        aliases=list(aliases),
        title=title or "",
        url=url,
        snippet=snippet,
    )


def parse_verdict(text: str | None) -> bool | None:
    word = (text or "").strip().strip(".!\"'`").lower()
    if word.startswith("yes"):
        return True
    if word.startswith("no"):
        return False
    return None


async def judge_answer(
    llm: LLMClient,
    *,
    query_text: str,
    field: str,
    value: Any,
    aliases: tuple[str, ...],
    title: str | None,
    url: str,
    snippet: str,
) -> tuple[bool | None, dict[str, str] | None]:
    prompt = build_answer_prompt(
        query_text=query_text,
        field=field,
        value=value,
        aliases=aliases,
        title=title,
        url=url,
        snippet=snippet,
    )
    return await complete_parsed(
        llm, prompt, parse_verdict, retry_suffix=VERDICT_RETRY_SUFFIX, max_tokens=8192
    )
