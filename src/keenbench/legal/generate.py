import itertools
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from keenbench.legal.models import Case, CodeSection, build_case_row, build_code_row
from keenbench.legal.projection import (
    CASELAW_SYNTAX_CYCLE,
    CODE_SYNTAX_CYCLE,
    build_code_prompt,
    caption_query,
    caselaw_syntax_query,
    clean_code_query,
    code_query_ok,
    code_syntax_query,
    party_tokens,
)
from keenbench.legal.sources import CourtListenerClient, EcfrClient, month_windows
from keenbench.shared.concurrency import bounded_gather
from keenbench.shared.llm import LLMClient
from keenbench.shared.sampling import dedupe_by, interleave

CODE_OVERSAMPLE = 3


@dataclass
class GenStats:
    case_candidates: int = 0
    caselaw_rows: int = 0
    generic_caption: int = 0
    section_candidates: int = 0
    code_rows: int = 0
    section_fetch_fail: int = 0
    code_no_query: int = 0
    code_rejected: int = 0
    llm_errors: int = 0
    llm_error_sample: str = ""
    short_courts: int = 0
    short_titles: int = 0


async def _caselaw_rows(
    courtlistener: CourtListenerClient,
    *,
    courts: tuple[str, ...],
    per_court: int,
    months_back: int,
    seed: int,
    hour_ts: datetime,
    now: datetime,
    stats: GenStats,
) -> list[dict[str, Any]]:
    windows = month_windows(now=now, months_back=months_back)
    rows: list[dict[str, Any]] = []
    syntax_cycle = itertools.cycle(CASELAW_SYNTAX_CYCLE)
    seen_clusters: set[int] = set()

    async def fetch_court(court: str) -> list[Case]:
        lists = await bounded_gather(
            windows,
            lambda w: courtlistener.opinions(court, filed_after=w[0], filed_before=w[1]),
            concurrency=2,
        )
        for wi, cases in enumerate(lists):
            random.Random(seed + wi).shuffle(cases)
        return interleave(lists)

    court_cases = await bounded_gather(list(courts), fetch_court, concurrency=2)

    for cases in court_cases:
        kept = 0
        for case in cases:
            if kept >= per_court:
                break
            if case.cluster_id in seen_clusters:
                continue
            seen_clusters.add(case.cluster_id)
            stats.case_candidates += 1
            base = caption_query(case)
            if base is None:
                stats.generic_caption += 1
                continue
            syntax = next(syntax_cycle)
            query_text = caselaw_syntax_query(case, base, syntax)
            rows.append(
                build_case_row(
                    case,
                    query_text=query_text,
                    syntax=syntax,
                    party_tokens=party_tokens(case.case_name),
                    hour_ts=hour_ts,
                )
            )
            kept += 1
        if kept < per_court:
            stats.short_courts += 1
    stats.caselaw_rows = len(rows)
    return rows


async def _code_rows(
    ecfr: EcfrClient,
    llm: LLMClient,
    *,
    titles: tuple[int, ...],
    per_title: int,
    seed: int,
    hour_ts: datetime,
    code_concurrency: int,
    stats: GenStats,
) -> list[dict[str, Any]]:
    async def title_sections(title_num: int) -> list[tuple[int, str, str, str]]:
        entries = await ecfr.sections(title_num, n=per_title * CODE_OVERSAMPLE, seed=seed)
        return [(title_num, part, identifier, label) for part, identifier, label in entries]

    section_lists = await bounded_gather(list(titles), title_sections, concurrency=2)

    async def project(
        entry: tuple[int, str, str, str],
    ) -> tuple[int, CodeSection | None, str | None, str | tuple[str, str] | None]:
        title_num, part, identifier, label = entry
        section = await ecfr.section(title_num, part, identifier, label)
        if section is None:
            return title_num, None, None, "fetch"
        try:
            text, err = await llm.complete(
                build_code_prompt(section), max_tokens=1024, reasoning_effort="minimal"
            )
        except Exception as exc:
            return title_num, None, None, ("llm_error", str(exc)[:200])
        if err is not None:
            sample = f"{err.get('error_type')}: {err.get('error_message')}"[:200]
            return title_num, None, None, ("llm_error", sample)
        query = clean_code_query(text)
        if query is None:
            return title_num, None, None, "no_query"
        if not code_query_ok(query, section=section):
            return title_num, None, None, "rejected"
        return title_num, section, query, None

    all_entries = [e for lst in section_lists for e in lst]
    stats.section_candidates = len(all_entries)
    projected = await bounded_gather(all_entries, project, concurrency=code_concurrency)

    drop_stat = {
        "fetch": "section_fetch_fail",
        "llm_error": "llm_errors",
        "no_query": "code_no_query",
        "rejected": "code_rejected",
    }
    by_title: dict[int, list[tuple[CodeSection, str]]] = {t: [] for t in titles}
    for title_num, section, query, drop in projected:
        if drop is not None:
            key, sample = drop if isinstance(drop, tuple) else (drop, None)
            setattr(stats, drop_stat[key], getattr(stats, drop_stat[key]) + 1)
            if sample and not stats.llm_error_sample:
                stats.llm_error_sample = sample
        elif section is not None and query is not None:
            by_title[title_num].append((section, query))

    rows: list[dict[str, Any]] = []
    syntax_cycle = itertools.cycle(CODE_SYNTAX_CYCLE)
    for title_num in titles:
        selected = by_title[title_num][:per_title]
        if len(selected) < per_title:
            stats.short_titles += 1
        for section, query in selected:
            syntax = next(syntax_cycle)
            rows.append(
                build_code_row(
                    section,
                    query_text=code_syntax_query(query, syntax),
                    syntax=syntax,
                    hour_ts=hour_ts,
                )
            )
    stats.code_rows = len(rows)
    return rows


async def run_generate(
    *,
    courtlistener: CourtListenerClient | None,
    ecfr: EcfrClient | None,
    llm: LLMClient | None,
    hour_ts: datetime,
    now: datetime,
    courts: tuple[str, ...],
    per_court: int,
    months_back: int,
    titles: tuple[int, ...],
    per_title: int,
    seed: int,
    code_concurrency: int = 8,
) -> tuple[list[dict[str, Any]], GenStats]:
    stats = GenStats()
    rows: list[dict[str, Any]] = []
    if courtlistener is not None:
        rows.extend(
            await _caselaw_rows(
                courtlistener,
                courts=courts,
                per_court=per_court,
                months_back=months_back,
                seed=seed,
                hour_ts=hour_ts,
                now=now,
                stats=stats,
            )
        )
    if ecfr is not None and llm is not None:
        rows.extend(
            await _code_rows(
                ecfr,
                llm,
                titles=titles,
                per_title=per_title,
                seed=seed,
                hour_ts=hour_ts,
                code_concurrency=code_concurrency,
                stats=stats,
            )
        )
    return dedupe_by(rows, lambda row: row["query_id"]), stats
