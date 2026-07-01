import asyncio
from typing import Any

from keenbench.shared.llm import LLMClient
from keenbench.shared.prompts import render_prompt

PROJECTION_TEMPLATE = "projection.jinja"


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


async def project_one(
    llm: LLMClient, record: dict[str, Any], *, today: str
) -> tuple[str | None, dict[str, str] | None]:
    prompt = build_projection_prompt(record, today=today)
    text, err = await llm.complete(prompt, max_tokens=512, reasoning_effort="minimal")
    if err is not None:
        return None, err
    if not text:
        return None, None
    cleaned = text.strip().splitlines()[0].strip(" \"'")
    if not cleaned or cleaned.upper() == "NO_NEWS_EVENT":
        return None, None
    return cleaned, None


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
