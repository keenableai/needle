from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from needle.news.trends import Trend
from needle.shared.concurrency import bounded_gather
from needle.shared.llm import LLMClient
from needle.shared.prompts import clean_llm_line, render_prompt

PROJECTION_TEMPLATE = "projection.jinja"
TRENDS_TEMPLATE = "trends_projection.jinja"

T = TypeVar("T")


def clean_projection(text: str | None) -> str | None:
    return clean_llm_line(text, sentinel="NO_NEWS_EVENT", strip_chars=" \"'")


def build_projection_prompt(record: dict[str, Any], *, today: str) -> str:
    return render_prompt(
        __package__,
        PROJECTION_TEMPLATE,
        today=today,
        source_kind=record.get("source_kind") or "",
        title=record.get("title") or "",
        summary=(record.get("summary") or "")[:500],
        url=record.get("url") or "",
    )


def build_trend_prompt(trend: Trend, *, today: str) -> str:
    lines = [f"  - [{n.source or ''}] {n.title or ''}" for n in trend.news_items[:5]]
    news_block = "\n".join(lines) if lines else "  (no news articles)"
    return render_prompt(
        __package__, TRENDS_TEMPLATE, today=today, topic=trend.topic, news_block=news_block
    )


async def project_batch(
    llm: LLMClient,
    items: Sequence[T],
    build_prompt: Callable[[T], str],
    *,
    concurrency: int = 8,
) -> list[tuple[T, str | None, dict[str, str] | None]]:
    async def _one(item: T) -> tuple[T, str | None, dict[str, str] | None]:
        try:
            text, err = await llm.complete(
                build_prompt(item), max_tokens=512, reasoning_effort="minimal"
            )
        except Exception as exc:
            return item, None, {"error_type": "projection_crash", "error_message": str(exc)[:500]}
        if err is not None:
            return item, None, err
        return item, clean_projection(text), None

    return await bounded_gather(items, _one, concurrency=concurrency)
