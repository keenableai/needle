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
    short_courts: int = 0
    short_titles: int = 0


def _interleave(lists: list[list[Any]]) -> list[Any]:
    merged: list[Any] = []
    for i in range(max((len(x) for x in lists), default=0)):
        for x in lists:
            if i < len(x):
                merged.append(x[i])
    return merged


async def _caselaw_rows(
    courtlistener: CourtListenerClient,
    *,
    courts: tuple[str, ...],
    per_court: int,
    months_back: int,
    hour_ts: datetime,
    now: datetime,
    stats: GenStats,
) -> list[dict[str, Any]]:
    windows = month_windows(now=now, months_back=months_back)
    rows: list[dict[str, Any]] = []
    syntax_idx = 0
    seen_clusters: set[int] = set()

    async def fetch_court(court: str) -> list[Case]:
        lists = await bounded_gather(
            windows,
            lambda w: courtlistener.opinions(court, filed_after=w[0], filed_before=w[1]),
            concurrency=2,
        )
        return _interleave(lists)

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
            syntax = CASELAW_SYNTAX_CYCLE[syntax_idx % len(CASELAW_SYNTAX_CYCLE)]
            syntax_idx += 1
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
    ) -> tuple[int, CodeSection | None, str | None, str | None]:
        title_num, part, identifier, label = entry
        section = await ecfr.section(title_num, part, identifier, label)
        if section is None:
            return title_num, None, None, "fetch"
        try:
            text, err = await llm.complete(
                build_code_prompt(section), max_tokens=256, reasoning_effort="minimal"
            )
        except Exception:
            return title_num, None, None, "llm_error"
        if err is not None:
            return title_num, None, None, "llm_error"
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
            setattr(stats, drop_stat[drop], getattr(stats, drop_stat[drop]) + 1)
        elif section is not None and query is not None:
            by_title[title_num].append((section, query))

    rows: list[dict[str, Any]] = []
    syntax_idx = 0
    for title_num in titles:
        selected = by_title[title_num][:per_title]
        if len(selected) < per_title:
            stats.short_titles += 1
        for section, query in selected:
            syntax = CODE_SYNTAX_CYCLE[syntax_idx % len(CODE_SYNTAX_CYCLE)]
            syntax_idx += 1
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
    seen_ids: set[str] = set()
    unique_rows = []
    for row in rows:
        if row["query_id"] in seen_ids:
            continue
        seen_ids.add(row["query_id"])
        unique_rows.append(row)
    return unique_rows, stats
