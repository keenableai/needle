import asyncio
import itertools
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from needle.coding.models import Doc, build_row
from needle.coding.projection import SYNTAX_CYCLES, build_prompt, query_ok, syntax_query
from needle.coding.sources import (
    ApiDocsClient,
    ChangelogClient,
    GitHubClient,
    MintlifyClient,
    StackExchangeClient,
)
from needle.shared.concurrency import bounded_gather
from needle.shared.llm import GENERATION_MAX_TOKENS, REASONING_EFFORT, LLMClient
from needle.shared.prompts import clean_llm_line
from needle.shared.sampling import dedupe_by, interleave, month_windows

OVERSAMPLE = 3


@dataclass
class GenStats:
    candidates: dict[str, int] = field(default_factory=dict)
    no_query: int = 0
    rejected: int = 0
    llm_errors: int = 0
    llm_error_sample: str = ""
    source_errors: list[str] = field(default_factory=list)


async def _windowed(
    fetch: Callable[..., Awaitable[list[Doc]]],
    keys: tuple[str, ...],
    *,
    windows: list[tuple[date, date]],
    seed: int,
) -> list[Doc]:
    async def one(key: str) -> list[Doc]:
        rng = random.Random(f"{seed}:{key}")
        after, before = rng.choice(windows)
        docs = await fetch(key, created_after=after, created_before=before)
        rng.shuffle(docs)
        return docs

    return interleave(await bounded_gather(list(keys), one, concurrency=2))


async def _issues(
    github: GitHubClient,
    repos: tuple[str, ...],
    *,
    now: datetime,
    months_back: int,
    seed: int,
    n: int,
) -> list[Doc]:
    repos = repos or tuple(await github.small_repos(now=now, seed=seed, n=n))
    windows = month_windows(now=now, months_back=months_back)
    full_range = [(min(a for a, _ in windows), max(b for _, b in windows))]
    return await _windowed(github.issues, repos, windows=full_range, seed=seed)


async def _project(doc: Doc, llm: LLMClient, stats: GenStats) -> str | None:
    try:
        text, err = await llm.complete(
            build_prompt(doc),
            max_tokens=GENERATION_MAX_TOKENS,
            reasoning_effort=REASONING_EFFORT,
        )
    except Exception as exc:
        text, err = None, {"error_type": type(exc).__name__, "error_message": str(exc)}
    if err is not None:
        stats.llm_errors += 1
        stats.llm_error_sample = (
            stats.llm_error_sample or (f"{err.get('error_type')}: {err.get('error_message')}"[:200])
        )
        return None
    query = clean_llm_line(text, sentinel="NO_DISTINCT_QUERY")
    if query is None:
        stats.no_query += 1
    elif not query_ok(query, doc):
        stats.rejected += 1
        query = None
    return query


async def run_generate(
    *,
    api: ApiDocsClient | None,
    github: GitHubClient | None,
    stackexchange: StackExchangeClient | None,
    llm: LLMClient,
    hour_ts: datetime,
    mintlify: MintlifyClient | None = None,
    changelogs: ChangelogClient | None = None,
    now: datetime,
    counts: dict[str, int],
    repos: tuple[str, ...],
    tags: tuple[str, ...],
    months_back: int,
    seed: int,
    concurrency: int = 8,
) -> tuple[list[dict[str, Any]], GenStats]:
    n = {t: c * OVERSAMPLE for t, c in counts.items()}
    fetches: dict[str, Awaitable[list[Doc]]] = {}
    if api is not None:
        fetches["api"] = api.docs(n=n["api"], seed=seed)
    if github is not None:
        fetches["issue"] = _issues(
            github, repos, now=now, months_back=months_back, seed=seed, n=n["issue"]
        )
    if mintlify is not None:
        fetches["mintlify"] = mintlify.docs(n=n["mintlify"], seed=seed)
    if changelogs is not None:
        fetches["fresh"] = changelogs.docs(n=n["fresh"], seed=seed, now=now)
    if stackexchange is not None:
        fetches["qa"] = _windowed(
            stackexchange.questions,
            tags,
            windows=month_windows(now=now, months_back=months_back),
            seed=seed,
        )
    found = await asyncio.gather(*fetches.values())
    candidates = {
        t: dedupe_by(docs, lambda d: d.key)[: n[t]] for t, docs in zip(fetches, found, strict=True)
    }

    stats = GenStats(
        candidates={t: len(docs) for t, docs in candidates.items()},
        source_errors=[
            e
            for client in (api, github, mintlify, changelogs, stackexchange)
            if client is not None
            for e in client.errors
        ],
    )
    docs = [d for type_docs in candidates.values() for d in type_docs]
    queries = await bounded_gather(docs, lambda d: _project(d, llm, stats), concurrency=concurrency)

    rows: list[dict[str, Any]] = []
    for doc_type in candidates:
        kept = [
            (d, q)
            for d, q in zip(docs, queries, strict=True)
            if q is not None and d.doc_type == doc_type
        ]
        syntax_cycle = itertools.cycle(SYNTAX_CYCLES[doc_type])
        for doc, query in kept[: counts[doc_type]]:
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
