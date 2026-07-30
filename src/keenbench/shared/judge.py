import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from typing import TypeVar

import yaml

from keenbench.shared.llm import MAX_ERROR_CHARS, LLMClient
from keenbench.shared.prompts import render_prompt

T = TypeVar("T")

DEFAULT_MAX_CONTENT_CHARS = 50_000
JUDGE_TEMPLATE = "judgement.jinja"
PROFILE_TEMPLATE = "query_profile.jinja"
RETRY_PREFIX = "\n\nYour previous reply could not be parsed. Respond with only the YAML fields:"
PARSE_RETRY_SUFFIX = RETRY_PREFIX + " rating (an integer 0-4), label, reasoning."
PROFILE_RETRY_SUFFIX = (
    RETRY_PREFIX + " objective, core_aspects, query_type (A, B, or C),"
    " archetype (Ephemeral, Persistent, or Evergreen), dated_event (true or false)."
)

QUERY_TYPES = frozenset({"A", "B", "C"})
ARCHETYPES = {"ephemeral": "Ephemeral", "persistent": "Persistent", "evergreen": "Evergreen"}

RATING_LABELS = {0: "FailsM", 1: "FailsM", 2: "SM", 3: "HM", 4: "FullyM"}
VALID_LABELS = frozenset({"FailsM", "SM", "MM", "HM", "FullyM"})

FENCE_PATTERNS = (
    re.compile(r"[ \t]*```(?:ya?ml|json)[ \t]*\n(.*?)\n[ \t]*```", re.DOTALL | re.IGNORECASE),
    re.compile(r"[ \t]*```[ \t]*\n(.*?)\n[ \t]*```", re.DOTALL),
    re.compile(r"[ \t]*```(?:ya?ml|json)[ \t]*(.*?)```", re.DOTALL | re.IGNORECASE),
    re.compile(r"```(.*?)```", re.DOTALL),
    re.compile(r"[ \t]*```(?:ya?ml|json)[ \t]*\n?(.*)", re.DOTALL | re.IGNORECASE),
    re.compile(r"[ \t]*```[ \t]*\n?(.*)", re.DOTALL),
)


def _extract_yaml_block(content: str) -> str:
    content = content.strip()
    for pattern in FENCE_PATTERNS:
        match = pattern.search(content)
        if match:
            return match.group(1).strip()
    return content


@dataclass(frozen=True)
class Judgement:
    rating: int
    label: str
    reasoning: str


@dataclass(frozen=True)
class QueryProfile:
    query_type: str
    archetype: str
    dated_event: bool
    objective: str
    core_aspects: tuple[str, ...]


def _profile_lines(profile: QueryProfile) -> list[str]:
    lines = [
        "**Query Analysis** (precomputed — adopt as ground truth, do not re-classify):",
        f"- Query type: {profile.query_type}",
        f"- Content archetype: {profile.archetype}",
        f"- Specific dated current-event query: {'yes' if profile.dated_event else 'no'}",
    ]
    if profile.objective:
        lines.append(f"- Objective: {profile.objective}")
    if profile.core_aspects:
        lines.append("- CORE aspects:")
        lines += [f"  - {aspect}" for aspect in profile.core_aspects]
    return lines


def build_user_message(
    query: str,
    *,
    url: str,
    title: str | None = None,
    published: str | None = None,
    content: str | None = None,
    today: str,
    max_content_chars: int = DEFAULT_MAX_CONTENT_CHARS,
    profile: QueryProfile | None = None,
) -> str:
    lines = [
        f"Today's date: {today}",
        "",
        f"**Query**: {query}",
        "",
    ]
    if profile is not None:
        lines += _profile_lines(profile) + [""]
    lines += [
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
    profile: QueryProfile | None = None,
) -> str:
    user = build_user_message(
        query,
        url=url,
        title=title,
        published=published,
        content=content,
        today=today,
        max_content_chars=max_content_chars,
        profile=profile,
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
    if label not in VALID_LABELS:
        label = RATING_LABELS[rating]
    reasoning = str(data.get("reasoning") or "")
    return Judgement(rating=rating, label=label, reasoning=reasoning)


def parse_query_profile(text: str | None) -> QueryProfile | None:
    if not text:
        return None
    data = _load_judgement_dict(_extract_yaml_block(text))
    if data is None:
        return None
    query_type = str(data.get("query_type") or "").strip().upper()[:1]
    archetype = ARCHETYPES.get(str(data.get("archetype") or "").strip().lower())
    if query_type not in QUERY_TYPES or archetype is None:
        return None
    dated = data.get("dated_event")
    if not isinstance(dated, bool):
        dated = str(dated).strip().lower() in {"true", "yes", "1"}
    aspects = data.get("core_aspects")
    if not isinstance(aspects, list):
        aspects = []
    return QueryProfile(
        query_type=query_type,
        archetype=archetype,
        dated_event=dated,
        objective=str(data.get("objective") or "").strip(),
        core_aspects=tuple(s for a in aspects if (s := str(a).strip())),
    )


async def complete_parsed(
    llm: LLMClient,
    prompt: str,
    parse: Callable[[str | None], T | None],
    *,
    retry_suffix: str,
    max_tokens: int,
) -> tuple[T | None, dict[str, str] | None]:
    for attempt_prompt in (prompt, prompt + retry_suffix):
        text, err = await llm.complete(
            attempt_prompt, max_tokens=max_tokens, reasoning_effort="minimal"
        )
        if err is not None:
            return None, err
        parsed = parse(text)
        if parsed is not None:
            return parsed, None
    return None, {
        "error_type": "judge_parse_error",
        "error_message": (text or "")[:MAX_ERROR_CHARS],
    }


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
    profile: QueryProfile | None = None,
) -> tuple[Judgement | None, dict[str, str] | None]:
    prompt = build_judge_prompt(
        query,
        url=url,
        title=title,
        published=published,
        content=content,
        today=today,
        max_content_chars=max_content_chars,
        profile=profile,
    )
    return await complete_parsed(
        llm, prompt, parse_judgement, retry_suffix=PARSE_RETRY_SUFFIX, max_tokens=32_768
    )


async def classify_query(
    llm: LLMClient, query: str, *, today: str
) -> tuple[QueryProfile | None, dict[str, str] | None]:
    prompt = render_prompt("keenbench.shared", PROFILE_TEMPLATE, query=query, today=today)
    return await complete_parsed(
        llm, prompt, parse_query_profile, retry_suffix=PROFILE_RETRY_SUFFIX, max_tokens=32_768
    )
