import json
import re
from collections.abc import Callable
from dataclasses import dataclass
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
    RETRY_PREFIX + " query_type (broad, specific, or list), query_domain,"
    " query_search_operators_exist (yes or no), query_main_aspects, query_aux_aspects,"
    " query_content_archetype (ephemeral, persistent, or evergreen)."
)

QUERY_TYPE_RE = re.compile(r"\b(broad|specific|list)\b")
ARCHETYPE_RE = re.compile(r"ephemeral|persistent|evergreen")
DOMAIN_RE = re.compile(r"health|legal|financial|academic|tech|news|commerce|jobs")

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
    query_domain: str
    query_search_operators_exist: bool
    query_main_aspects: tuple[str, ...]
    query_aux_aspects: tuple[str, ...]
    query_content_archetype: str


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
    if content and 0 < max_content_chars < len(content):
        head, tail = content[:max_content_chars], content[max_content_chars:]
        content = (
            f"{head}\n... and another {len(tail.split())} words "
            f"({len(tail)} characters) not shown ..."
        )
    return render_prompt(
        "keenbench.shared",
        JUDGE_TEMPLATE,
        query=query,
        url=url,
        title=title or "",
        published=published,
        content=content,
        today=today,
        profile=profile,
    )


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


def _clean_line(raw: object) -> str:
    return " ".join(str(raw).split())


def _aspect_tuple(raw: object) -> tuple[str, ...]:
    if isinstance(raw, list):
        return tuple(s for a in raw if (s := _clean_line(a)))
    cleaned = _clean_line(raw or "")
    return (cleaned,) if cleaned else ()


def parse_query_profile(text: str | None) -> QueryProfile | None:
    if not text:
        return None
    data = _load_judgement_dict(_extract_yaml_block(text))
    if data is None:
        return None
    type_match = QUERY_TYPE_RE.search(str(data.get("query_type") or "").lower())
    arch_match = ARCHETYPE_RE.search(str(data.get("query_content_archetype") or "").lower())
    if type_match is None or arch_match is None:
        return None
    domain_match = DOMAIN_RE.search(str(data.get("query_domain") or "").lower())
    operators = data.get("query_search_operators_exist")
    if not isinstance(operators, bool):
        operators = str(operators).strip().lower() in {"true", "yes", "1"}
    return QueryProfile(
        query_type=type_match.group(1),
        query_domain=domain_match.group(0) if domain_match else "other",
        query_search_operators_exist=operators,
        query_main_aspects=_aspect_tuple(data.get("query_main_aspects")),
        query_aux_aspects=_aspect_tuple(data.get("query_aux_aspects")),
        query_content_archetype=arch_match.group(0),
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
