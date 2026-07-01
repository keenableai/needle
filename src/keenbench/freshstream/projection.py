import asyncio
from typing import Any

from keenbench.freshstream.trends import Trend
from keenbench.shared.llm import LLMClient
from keenbench.shared.prompts import render_prompt

PROJECTION_TEMPLATE = "projection.jinja"
TRENDS_TEMPLATE = "trends_projection.jinja"


def clean_projection(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = text.strip().splitlines()[0].strip(" \"'")
    if not cleaned or cleaned.upper() == "NO_NEWS_EVENT":
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


async def project_one(
    llm: LLMClient, record: dict[str, Any], *, today: str
) -> tuple[str | None, dict[str, str] | None]:
    prompt = build_projection_prompt(record, today=today)
    text, err = await llm.complete(prompt, max_tokens=512, reasoning_effort="minimal")
    if err is not None:
        return None, err
    return clean_projection(text), None


async def project_trend_one(
    llm: LLMClient, trend: Trend, *, today: str
) -> tuple[str | None, dict[str, str] | None]:
    prompt = build_trend_prompt(trend, today=today)
    text, err = await llm.complete(prompt, max_tokens=512, reasoning_effort="minimal")
    if err is not None:
        return None, err
    return clean_projection(text), None


async def project_all(
    llm: LLMClient,
    records: list[dict[str, Any]],
    *,
    today: str,
    concurrency: int = 8,
) -> list[tuple[dict[str, Any], str | None, dict[str, str] | None]]:
    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")
    sem = asyncio.Semaphore(concurrency)

    async def _one(
        r: dict[str, Any],
    ) -> tuple[dict[str, Any], str | None, dict[str, str] | None]:
        async with sem:
            try:
                text, err = await project_one(llm, r, today=today)
            except Exception as exc:
                return r, None, {"error_type": "projection_crash", "error_message": str(exc)[:500]}
            return r, text, err

    return list(await asyncio.gather(*[_one(r) for r in records]))


async def project_trends(
    llm: LLMClient,
    trends: list[Trend],
    *,
    today: str,
    concurrency: int = 8,
) -> list[tuple[Trend, str | None, dict[str, str] | None]]:
    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")
    sem = asyncio.Semaphore(concurrency)

    async def _one(t: Trend) -> tuple[Trend, str | None, dict[str, str] | None]:
        async with sem:
            try:
                text, err = await project_trend_one(llm, t, today=today)
            except Exception as exc:
                return t, None, {"error_type": "projection_crash", "error_message": str(exc)[:500]}
            return t, text, err

    return list(await asyncio.gather(*[_one(t) for t in trends]))
