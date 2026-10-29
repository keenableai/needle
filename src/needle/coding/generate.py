import hashlib
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from needle.coding.models import DocHost, DocPage, build_gold_row
from needle.coding.projection import (
    build_task_prompt,
    clean_task_query,
    task_query_ok,
    title_query,
    usable_body,
)
from needle.coding.sources import MintlifyClient, english_indexes, page_body, parse_llms
from needle.shared.concurrency import bounded_gather
from needle.shared.identity import canonicalize
from needle.shared.llm import LLMClient
from needle.shared.sampling import dedupe_by, shuffle_indices

TASK_OVERSAMPLE = 4
MAX_INDEX_FETCHES = 6


@dataclass
class GenStats:
    candidates: int = 0
    title_rows: int = 0
    task_rows: int = 0
    task_no_query: int = 0
    task_rejected: int = 0
    fetch_fail: int = 0
    thin_pages: int = 0
    llm_errors: int = 0
    llm_error_sample: str = ""
    short_hosts: int = 0


def _host_seed(seed: int, slug: str) -> int:
    digest = hashlib.sha256(slug.encode()).digest()[:8]
    return seed ^ int.from_bytes(digest, "big")


def _order_indexes(urls: list[str], seed: int) -> list[str]:
    groups: dict[int, list[str]] = {}
    for url in urls:
        groups.setdefault(urlsplit(url).path.count("/"), []).append(url)
    ordered: list[str] = []
    for depth in sorted(groups, reverse=True):
        group = groups[depth]
        if len(group) > 1:
            perm = shuffle_indices(len(group), seed ^ depth)
            group = [group[i] for i in perm]
        ordered.extend(group)
    return ordered


async def _pages_for_host(
    client: MintlifyClient,
    host: DocHost,
    *,
    need: int,
    seed: int,
) -> tuple[list[DocPage], int]:
    root = await client.fetch_text(host.llms_url)
    if not root:
        return [], 1
    pages, indexes = parse_llms(root, product=host.product, base_url=host.llms_url)
    indexes = english_indexes(indexes)
    fetches = 0
    if indexes:
        pages = []
        queue = _order_indexes(indexes, _host_seed(seed, host.slug))
        seen = {host.llms_url}
        while queue and len(pages) < need and fetches < MAX_INDEX_FETCHES:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            text = await client.fetch_text(url)
            fetches += 1
            if not text:
                continue
            child_pages, child_indexes = parse_llms(text, product=host.product, base_url=url)
            child_indexes = english_indexes(child_indexes)
            if child_indexes:
                queue[0:0] = _order_indexes(child_indexes, _host_seed(seed, host.slug))
            known = {page.item_key for page in pages}
            pages.extend(page for page in child_pages if page.item_key not in known)
    if len(pages) > 1:
        perm = shuffle_indices(len(pages), _host_seed(seed, host.slug))
        pages = [pages[i] for i in perm]
    return pages[:need], fetches


async def run_generate(
    *,
    client: MintlifyClient,
    llm: LLMClient | None,
    hour_ts: datetime,
    hosts: tuple[DocHost, ...],
    per_host: int,
    seed: int,
    slices: tuple[str, ...] = ("title", "task"),
    task_concurrency: int = 8,
) -> tuple[list[dict[str, Any]], GenStats]:
    stats = GenStats()
    need = per_host * TASK_OVERSAMPLE

    async def collect(host: DocHost) -> tuple[DocHost, list[DocPage], int]:
        pages, fetches = await _pages_for_host(client, host, need=need, seed=seed)
        return host, pages, fetches

    collected = await bounded_gather(list(hosts), collect, concurrency=2)
    entries: list[tuple[DocHost, DocPage]] = []
    for host, pages, fetches in collected:
        stats.fetch_fail += fetches if not pages and fetches else 0
        entries.extend((host, page) for page in pages)
    stats.candidates = len(entries)
    if "task" not in slices:
        return _finish(
            _title_rows(entries, hosts, per_host=per_host, hour_ts=hour_ts, stats=stats), stats
        )

    if llm is None:
        raise ValueError("task slice requires an llm")

    async def load_body(
        entry: tuple[DocHost, DocPage],
    ) -> tuple[DocHost, DocPage | None, str | None]:
        host, page = entry
        text = await client.fetch_text(page.markdown_url)
        if not text:
            return host, None, "fetch"
        loaded = replace(page, body=page_body(text))
        if not usable_body(loaded):
            return host, None, "thin"
        return host, loaded, None

    loaded = await bounded_gather(entries, load_body, concurrency=task_concurrency)
    ready: list[tuple[DocHost, DocPage]] = []
    for host, page, reason in loaded:
        if reason == "fetch":
            stats.fetch_fail += 1
        elif reason == "thin":
            stats.thin_pages += 1
        elif page is not None:
            ready.append((host, page))

    async def project(
        entry: tuple[DocHost, DocPage],
    ) -> tuple[DocHost, DocPage, str | None, str | tuple[str, str] | None]:
        host, page = entry
        try:
            text, err = await llm.complete(
                build_task_prompt(page), max_tokens=256, reasoning_effort="minimal"
            )
        except Exception as exc:
            return host, page, None, ("llm_error", str(exc)[:200])
        if err is not None:
            sample = f"{err.get('error_type')}: {err.get('error_message')}"[:200]
            return host, page, None, ("llm_error", sample)
        query = clean_task_query(text)
        if query is None:
            return host, page, None, "no_query"
        if not task_query_ok(query, page=page):
            return host, page, None, "rejected"
        return host, page, query, None

    projected = await bounded_gather(ready, project, concurrency=task_concurrency)
    drop_stat = {
        "llm_error": "llm_errors",
        "no_query": "task_no_query",
        "rejected": "task_rejected",
    }
    by_host: dict[str, list[tuple[DocPage, str]]] = {host.slug: [] for host in hosts}
    for host, page, query, drop in projected:
        if drop is not None:
            key, sample = drop if isinstance(drop, tuple) else (drop, None)
            setattr(stats, drop_stat[key], getattr(stats, drop_stat[key]) + 1)
            if sample and not stats.llm_error_sample:
                stats.llm_error_sample = sample
        elif query is not None:
            by_host[host.slug].append((page, query))

    rows: list[dict[str, Any]] = []
    used: set[str] = set()
    for host in hosts:
        chosen = 0
        for page, query in by_host[host.slug]:
            texts = [title_query(page), query] if "title" in slices else [query]
            if not _claim(texts, used):
                continue
            if "title" in slices:
                rows.append(
                    build_gold_row(page, query_text=texts[0], bucket="title", hour_ts=hour_ts)
                )
            rows.append(build_gold_row(page, query_text=query, bucket="task", hour_ts=hour_ts))
            chosen += 1
            if chosen == per_host:
                break
        if chosen < per_host:
            stats.short_hosts += 1
    return _finish(rows, stats)


def _title_rows(
    entries: list[tuple[DocHost, DocPage]],
    hosts: tuple[DocHost, ...],
    *,
    per_host: int,
    hour_ts: datetime,
    stats: GenStats,
) -> list[dict[str, Any]]:
    by_host: dict[str, list[DocPage]] = {host.slug: [] for host in hosts}
    for host, page in entries:
        by_host[host.slug].append(page)
    rows: list[dict[str, Any]] = []
    used: set[str] = set()
    for host in hosts:
        chosen = 0
        for page in by_host[host.slug]:
            text = title_query(page)
            if not _claim([text], used):
                continue
            rows.append(build_gold_row(page, query_text=text, bucket="title", hour_ts=hour_ts))
            chosen += 1
            if chosen == per_host:
                break
        if chosen < per_host:
            stats.short_hosts += 1
    return rows


def _claim(texts: list[str], used: set[str]) -> bool:
    keys = [canonicalize(text) for text in texts]
    if len(set(keys)) != len(keys) or any(key in used for key in keys):
        return False
    used.update(keys)
    return True


def _finish(rows: list[dict[str, Any]], stats: GenStats) -> tuple[list[dict[str, Any]], GenStats]:
    kept = dedupe_by(rows, lambda row: row["query_id"])
    stats.title_rows = sum(1 for row in kept if row["query_origin"]["bucket"] == "title")
    stats.task_rows = sum(1 for row in kept if row["query_origin"]["bucket"] == "task")
    return kept, stats
