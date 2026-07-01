import json
import re
from dataclasses import dataclass
from functools import cache

import yaml

from keenbench.shared.llm import LLMClient
from keenbench.shared.prompts import render_prompt

DEFAULT_MAX_CONTENT_CHARS = 50_000
JUDGE_TEMPLATE = "judgement.jinja"

_LABELS = {0: "FailsM", 1: "FailsM", 2: "SM", 3: "HM", 4: "FullyM"}
_VALID_LABELS = frozenset({"FailsM", "SM", "MM", "HM", "FullyM"})

_FENCE_PATTERNS = (
    re.compile(r"[ \t]*```(?:ya?ml|json)[ \t]*\n(.*?)\n[ \t]*```", re.DOTALL | re.IGNORECASE),
    re.compile(r"[ \t]*```[ \t]*\n(.*?)\n[ \t]*```", re.DOTALL),
    re.compile(r"[ \t]*```(?:ya?ml|json)[ \t]*(.*?)```", re.DOTALL | re.IGNORECASE),
    re.compile(r"```(.*?)```", re.DOTALL),
    re.compile(r"[ \t]*```(?:ya?ml|json)[ \t]*\n?(.*)", re.DOTALL | re.IGNORECASE),
    re.compile(r"[ \t]*```[ \t]*\n?(.*)", re.DOTALL),
)


def _extract_yaml_block(content: str) -> str:
    content = content.strip()
    for pattern in _FENCE_PATTERNS:
        match = pattern.search(content)
        if match:
            return match.group(1).strip()
    return content


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


@cache
def _system_prompt() -> str:
    return render_prompt("keenbench.shared", JUDGE_TEMPLATE)


def build_judge_prompt(
    query: str,
    *,
    url: str,
    title: str | None = None,
    published: str | None = None,
    content: str | None = None,
    today: str,
    max_content_chars: int = DEFAULT_MAX_CONTENT_CHARS,
) -> str:
    user = build_user_message(
        query,
        url=url,
        title=title,
        published=published,
        content=content,
        today=today,
        max_content_chars=max_content_chars,
    )
    return _system_prompt() + "\n\n" + user


def _parse_rating(raw: object) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        try:
            return int(raw.strip())
        except ValueError:
            return None
    return None


def _extract_fields_regex(content: str) -> dict[str, object] | None:
    rating_match = re.search(r"^rating:\s*(\d+)", content, re.MULTILINE)
    label_match = re.search(r"^label:\s*(\S+)", content, re.MULTILINE)
    if not rating_match or not label_match:
        return None
    result: dict[str, object] = {
        "rating": int(rating_match.group(1)),
        "label": label_match.group(1).strip("\"'"),
    }
    reasoning_match = re.search(
        r"^reasoning:\s*(.*?)(?:\n[a-z_]+:|\Z)", content, re.MULTILINE | re.DOTALL
    )
    if reasoning_match:
        result["reasoning"] = reasoning_match.group(1).strip().strip("\"'")
    return result


def _load_judgement_dict(block: str) -> dict[str, object] | None:
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError:
        try:
            data = json.loads(block)
        except (json.JSONDecodeError, ValueError):
            data = _extract_fields_regex(block)
    return data if isinstance(data, dict) else None


def parse_judgement(text: str | None) -> Judgement | None:
    if not text:
        return None
    data = _load_judgement_dict(_extract_yaml_block(text))
    if data is None or "rating" not in data:
        return None
    rating = _parse_rating(data["rating"])
    if rating is None or not 0 <= rating <= 4:
        return None
    label = str(data.get("label") or "").strip()
    if label not in _VALID_LABELS:
        label = _LABELS[rating]
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
    text, err = await llm.complete(prompt, max_tokens=32_768, reasoning_effort="minimal")
    if err is not None:
        return None, err
    judgement = parse_judgement(text)
    if judgement is None:
        return None, {"error_type": "judge_parse_error", "error_message": (text or "")[:500]}
    return judgement, None
