import asyncio
from datetime import UTC, datetime
from typing import Any

from keenbench.shared.llm import LLMClient

PROJECTION_PROMPT = """\
Today's date: {today}

You are a search query generator for a search engine evaluation system. Generate a single search query that targets a specific news event happening today (within the past few hours) related to this recently-published article.

Requirements:
- Keyword-style query, not a natural language question
- 2-6 words, terse and direct
- The query MUST reference the specific event from the article, not just the person/team/topic in general (e.g. 'Lakers trade deadline' NOT just 'Lakers')
- Include the year or date where it helps disambiguate
- Do NOT copy article titles or URLs verbatim
- Do NOT start the query with 'what' or 'why' — use keyword style
- Always respond in English. If the article is not in English, respond with an English query anyways
- If the article's ideal answer would be the same a month from now (evergreen explainer, how-to, recipe collection, best-of list, gift guide, review of a stable product, historical retrospective, opinion piece), respond with exactly NO_NEWS_EVENT

Source kind: {source_kind}
Title: {title}
Summary: {summary}
URL: {url}

Respond with ONLY the query string (or NO_NEWS_EVENT). No quotes, no explanation, no JSON.
"""


def build_projection_prompt(record: dict[str, Any]) -> str:
    return PROJECTION_PROMPT.format(
        today=datetime.now(UTC).strftime("%Y-%m-%d"),
        source_kind=record.get("source_kind") or "",
        title=record.get("title") or "",
        summary=(record.get("summary") or "")[:500],
        url=record.get("url") or "",
    )


async def project_one(
    llm: LLMClient, record: dict[str, Any]
) -> tuple[str | None, dict[str, str] | None]:
    prompt = build_projection_prompt(record)
    text, err = await llm.complete(prompt, max_tokens=512, reasoning_effort="minimal")
    if err is not None:
        return None, err
    if not text:
        return None, None
    cleaned = text.strip().splitlines()[0].strip(" \"'")
    if not cleaned or "NO_NEWS_EVENT" in cleaned.upper():
        return None, None
    return cleaned, None


async def project_all(
    llm: LLMClient,
    records: list[dict[str, Any]],
    *,
    concurrency: int = 8,
) -> list[tuple[dict[str, Any], str | None, dict[str, str] | None]]:
    sem = asyncio.Semaphore(concurrency)

    async def _one(
        r: dict[str, Any],
    ) -> tuple[dict[str, Any], str | None, dict[str, str] | None]:
        async with sem:
            try:
                text, err = await project_one(llm, r)
            except Exception as exc:
                return r, None, {"error_type": "projection_crash", "error_message": str(exc)[:500]}
            return r, text, err

    return list(await asyncio.gather(*[_one(r) for r in records]))
