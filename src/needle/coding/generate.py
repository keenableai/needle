import itertools
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from needle.coding.models import DOC_TYPES, Doc, build_row
from needle.coding.projection import (
    SYNTAX_CYCLES,
    build_prompt,
    clean_query,
    query_ok,
    syntax_query,
)
from needle.coding.sources import ApiDocsClient, GitHubClient, StackExchangeClient
from needle.legal.sources import month_windows
from needle.shared.concurrency import bounded_gather
from needle.shared.llm import GENERATION_MAX_TOKENS, REASONING_EFFORT, LLMClient
from needle.shared.sampling import dedupe_by, interleave

OVERSAMPLE = 3

WindowFetch = Callable[..., Awaitable[list[Doc]]]


@dataclass
class GenStats:
    candidates: dict[str, int] = field(default_factory=dict)
    rows: dict[str, int] = field(default_factory=dict)
    no_query: int = 0
    rejected: int = 0
    llm_errors: int = 0
    llm_error_sample: str = ""


async def _windowed(
    fetch: WindowFetch, keys: tuple[str, ...], *, now: datetime, months_back: int, seed: int
) -> list[Doc]:
    windows = month_windows(now=now, months_back=months_back)

    async def one(key: str) -> list[Doc]:
        after, before = random.Random(f"{seed}:{key}").choice(windows)
        docs = await fetch(key, created_after=after, created_before=before)
        random.Random(f"{seed}:{key}:order").shuffle(docs)
        return docs

    return interleave(await bounded_gather(list(keys), one, concurrency=2))


async def _candidates(
    *,
    api: ApiDocsClient | None,
    github: GitHubClient | None,
    stackexchange: StackExchangeClient | None,
    n: int,
    repos: tuple[str, ...],
    tags: tuple[str, ...],
    now: datetime,
    months_back: int,
    seed: int,
) -> dict[str, list[Doc]]:
    found: dict[str, list[Doc]] = {}
    if api is not None:
        found["api"] = await api.docs(n=n, seed=seed)
    if github is not None:
        found["issue"] = await _windowed(
            github.issues, repos, now=now, months_back=months_back, seed=seed
        )
    if stackexchange is not None:
        found["qa"] = await _windowed(
            stackexchange.questions, tags, now=now, months_back=months_back, seed=seed
        )
    return {t: dedupe_by(docs, lambda d: d.key)[:n] for t, docs in found.items()}


async def _project(doc: Doc, llm: LLMClient) -> tuple[Doc, str | None, str, str]:
    try:
        text, err = await llm.complete(
            build_prompt(doc),
            max_tokens=GENERATION_MAX_TOKENS,
            reasoning_effort=REASONING_EFFORT,
        )
    except Exception as exc:
        return doc, None, "llm_errors", str(exc)[:200]
    if err is not None:
        return doc, None, "llm_errors", f"{err.get('error_type')}: {err.get('error_message')}"[:200]
    query = clean_query(text)
    if query is None:
        return doc, None, "no_query", ""
    if not query_ok(query, doc):
        return doc, None, "rejected", ""
    return doc, query, "", ""


async def run_generate(
    *,
    api: ApiDocsClient | None,
    github: GitHubClient | None,
    stackexchange: StackExchangeClient | None,
    llm: LLMClient,
    hour_ts: datetime,
    now: datetime,
    per_type: int,
    repos: tuple[str, ...],
    tags: tuple[str, ...],
    months_back: int,
    seed: int,
    concurrency: int = 8,
) -> tuple[list[dict[str, Any]], GenStats]:
    stats = GenStats()
    candidates = await _candidates(
        api=api,
        github=github,
        stackexchange=stackexchange,
        n=per_type * OVERSAMPLE,
        repos=repos,
        tags=tags,
        now=now,
        months_back=months_back,
        seed=seed,
    )
    docs = [d for t in DOC_TYPES for d in candidates.get(t, [])]
    projected = await bounded_gather(docs, lambda d: _project(d, llm), concurrency=concurrency)

    kept: dict[str, list[tuple[Doc, str]]] = {t: [] for t in candidates}
    for doc, query, drop, sample in projected:
        if query is not None:
            kept[doc.doc_type].append((doc, query))
            continue
        setattr(stats, drop, getattr(stats, drop) + 1)
        if sample and not stats.llm_error_sample:
            stats.llm_error_sample = sample

    rows: list[dict[str, Any]] = []
    for doc_type in DOC_TYPES:
        if doc_type not in candidates:
            continue
        selected = kept[doc_type][:per_type]
        stats.candidates[doc_type] = len(candidates[doc_type])
        stats.rows[doc_type] = len(selected)
        syntax_cycle = itertools.cycle(SYNTAX_CYCLES[doc_type])
        for doc, query in selected:
            syntax = next(syntax_cycle)
            rows.append(
                build_row(
                    doc,
                    query_text=syntax_query(query, doc, syntax),
                    syntax=syntax,
                    hour_ts=hour_ts,
                )
            )
    return dedupe_by(rows, lambda row: row["query_id"]), stats
