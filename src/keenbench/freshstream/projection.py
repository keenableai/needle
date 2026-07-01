import asyncio
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from keenbench.freshstream.trends import Trend
from keenbench.shared.llm import LLMClient
from keenbench.shared.prompts import render_prompt

PROJECTION_TEMPLATE = "projection.jinja"
TRENDS_TEMPLATE = "trends_projection.jinja"

T = TypeVar("T")


def clean_projection(text: str | None) -> str | None:
    text = (text or "").strip()
    if not text:
        return None
    cleaned = text.splitlines()[0].strip(" \"'")
    # Substring, not equality: refusals arrive with punctuation or prefixes
    # ("NO_NEWS_EVENT.", "Answer: NO_NEWS_EVENT") and must not become queries.
    if not cleaned or "NO_NEWS_EVENT" in cleaned.upper():
        return None
    return cleaned


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
    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")
    sem = asyncio.Semaphore(concurrency)

    async def _one(item: T) -> tuple[T, str | None, dict[str, str] | None]:
        async with sem:
            try:
                text, err = await llm.complete(
                    build_prompt(item), max_tokens=512, reasoning_effort="minimal"
                )
            except Exception as exc:
                return (
                    item,
                    None,
                    {"error_type": "projection_crash", "error_message": str(exc)[:500]},
                )
        if err is not None:
            return item, None, err
        return item, clean_projection(text), None

    return list(await asyncio.gather(*[_one(item) for item in items]))
