from typing import Any

from keenbench.shared.llm import LLMClient
from keenbench.shared.prompts import render_prompt

ANSWER_TEMPLATE = "answer_match.jinja"


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
        "keenbench.companyfill",
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
    text, err = await llm.complete(prompt, max_tokens=8192, reasoning_effort="minimal")
    if err is not None:
        return None, err
    verdict = parse_verdict(text)
    if verdict is None:
        return None, {"error_type": "judge_parse_error", "error_message": (text or "")[:500]}
    return verdict, None
