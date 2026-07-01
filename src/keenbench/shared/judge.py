import re
from dataclasses import dataclass
from typing import Any

import yaml

from keenbench.shared.llm import LLMClient
from keenbench.shared.prompts import render_prompt

DEFAULT_MAX_CONTENT_CHARS = 50_000
JUDGE_TEMPLATE = "judgement_no_qid.jinja"

_LABELS = {0: "FailsM", 1: "FailsM", 2: "SM", 3: "HM", 4: "FullyM"}
_FENCE_RE = re.compile(r"```(?:yaml)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class Judgement:
    rating: int
    label: str
    reasoning: str


def build_user_message(
    query: str,
    *,
    url: str,
    title: str | None = None,
    published: str | None = None,
    content: str | None = None,
    today: str,
    max_content_chars: int = DEFAULT_MAX_CONTENT_CHARS,
) -> str:
    lines = [
        f"Today's date: {today}",
        "",
        f"**Query**: {query}",
        "",
        "**Document to evaluate**:",
        f"- Title: {title or ''}",
        f"- URL: {url}",
    ]
    if published:
        lines.append(f"- Published: {published}")
    if content:
        if max_content_chars > 0 and len(content) > max_content_chars:
            head, tail = content[:max_content_chars], content[max_content_chars:]
            content = (
                f"{head}\n... and another {len(tail.split())} words "
                f"({len(tail)} characters) not shown ..."
            )
        lines += ["- Page Content:", "<<<CONTENT>>>", content, "<<</CONTENT>>>"]
    return "\n".join(lines) + "\n"


def build_judge_prompt(query: str, **doc: Any) -> str:
    system = render_prompt("keenbench.shared", JUDGE_TEMPLATE)
    return system + "\n\n" + build_user_message(query, **doc)


def parse_judgement(text: str | None) -> Judgement | None:
    if not text:
        return None
    match = _FENCE_RE.search(text)
    body = match.group(1) if match else text
    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict) or "rating" not in data:
        return None
    try:
        rating = int(data["rating"])
    except (TypeError, ValueError):
        return None
    if not 0 <= rating <= 4:
        return None
    label = str(data.get("label") or _LABELS[rating])
    reasoning = str(data.get("reasoning") or "")
    return Judgement(rating=rating, label=label, reasoning=reasoning)


async def judge_one(
    llm: LLMClient,
    query: str,
    *,
    url: str,
    title: str | None = None,
    published: str | None = None,
    content: str | None = None,
    today: str,
    max_content_chars: int = DEFAULT_MAX_CONTENT_CHARS,
) -> tuple[Judgement | None, dict[str, str] | None]:
    prompt = build_judge_prompt(
        query,
        url=url,
        title=title,
        published=published,
        content=content,
        today=today,
        max_content_chars=max_content_chars,
    )
    text, err = await llm.complete(prompt, max_tokens=1024, reasoning_effort="minimal")
    if err is not None:
        return None, err
    judgement = parse_judgement(text)
    if judgement is None:
        return None, {"error_type": "judge_parse_error", "error_message": (text or "")[:500]}
    return judgement, None
