import asyncio
import sys

from needle.coding.generate import GenStats, run_generate
from needle.coding.models import BUCKETS, DEFAULT_HOSTS, DocHost
from needle.coding.score import GoldCoding, run_coding
from needle.coding.sources import HOSTS, MintlifyClient
from needle.shared.cli import (
    aclose_all,
    build_clients_or_exit,
    current_hour,
    fmt_or_na,
    has_gold_ids,
    load_gold_rows,
    parse_csv,
    parse_known_csv,
    require_openrouter_client,
    resolve_seed,
    sample_or_exit,
)
from needle.shared.io import serialize_row, write_json, write_jsonl
from needle.shared.llm import resolve_llm_model
from needle.shared.search import DEFAULT_SNIPPET_CHARS


def _hosts(value: str | tuple[str, ...]) -> tuple[DocHost, ...]:
    names = tuple(parse_csv(value))
    if not names:
        raise SystemExit("error: --hosts must list at least one host")
    chosen: list[DocHost] = []
    for name in names:
        host = HOSTS.get(name.strip().lower())
        if host is None:
            known = ", ".join(DEFAULT_HOSTS)
            raise SystemExit(f"error: unknown host {name!r}; known: {known}")
        chosen.append(host)
    return tuple(chosen)


def _gold_coding(row: dict) -> GoldCoding:
    gold = row["gold"]
    origin = row.get("query_origin") or {}
    ids = gold.get("ids") or {}
    return GoldCoding(
        text=str(row["query_text"]),
        item_key=str(gold.get("item_key") or ids.get("page") or ""),
        bucket=str(origin.get("bucket") or "unknown"),
        page_key=str(ids.get("page") or gold.get("item_key") or ""),
        product=str(gold.get("product") or ""),
    )


class Coding:
    def generate(
        self,
        out: str = "-",
        hosts: str | tuple[str, ...] = ",".join(DEFAULT_HOSTS),
        per_host: int = 4,
        slices: str | tuple[str, ...] = "title,task",
        seed: int | None = None,
        llm_model: str | None = None,
        task_concurrency: int = 8,
    ) -> None:
        chosen = _hosts(hosts)
        chosen_slices = parse_known_csv(slices, BUCKETS, flag="--slices")
        if per_host < 1:
            raise SystemExit("error: --per-host must be >= 1")
        _, hour_ts = current_hour()
        seed = resolve_seed(seed, hour_ts)
        client = MintlifyClient()
        llm = None
        if "task" in chosen_slices:
            llm = require_openrouter_client(resolve_llm_model(llm_model), purpose="the task slice")

        async def _go() -> tuple[list[dict], GenStats]:
            try:
                return await run_generate(
                    client=client,
                    llm=llm,
                    hour_ts=hour_ts,
                    hosts=chosen,
                    per_host=per_host,
                    seed=seed,
                    slices=chosen_slices,
                    task_concurrency=task_concurrency,
                )
            finally:
                await aclose_all(client, llm)

        rows, stats = asyncio.run(_go())
        write_jsonl([serialize_row(r) for r in rows], out)
        print(
            f"coding: {stats.title_rows + stats.task_rows} queries "
            f"(title={stats.title_rows}, task={stats.task_rows} "
            f"of {stats.candidates} candidates; "
            f"drops: no_query={stats.task_no_query}, rejected={stats.task_rejected}, "
            f"fetch_fail={stats.fetch_fail}, thin={stats.thin_pages}, "
            f"llm_err={stats.llm_errors}, "
            f"short_hosts={stats.short_hosts})",
            file=sys.stderr,
        )
        if stats.llm_error_sample:
            print(f"coding first llm error: {stats.llm_error_sample}", file=sys.stderr)

    def run(
        self,
        queries: str,
        out: str = "-",
        engines: str | tuple[str, ...] = "keenable,exa",
        num_results: int = 5,
        snippet_chars: int = DEFAULT_SNIPPET_CHARS,
        limit: int = 0,
        sample: str = "stratified",
        seed: int | None = None,
    ) -> None:
        rows = load_gold_rows(queries, bench="coding", gold_ok=has_gold_ids)
        rows = sample_or_exit(
            rows,
            limit,
            seed,
            strategy=sample,
            key=lambda r: (
                f"{r['query_origin'].get('bucket', '?')}:{r['gold'].get('product') or '?'}"
            ),
        )
        gold_rows = [_gold_coding(r) for r in rows]
        clients = build_clients_or_exit(engines, snippet_chars=snippet_chars)

        async def _go() -> dict:
            try:
                return await run_coding(
                    gold_rows,
                    clients,
                    num_results=num_results,
                    snippet_chars=snippet_chars,
                )
            finally:
                await aclose_all(*clients.values())

        report = asyncio.run(_go())
        write_json(report, out)
        print(
            f"\ncoding: {report['num_queries']} queries, top-{num_results}",
            file=sys.stderr,
        )
        for name, engine in report["engines"].items():
            title = engine["by_bucket"].get("title", {}).get("recall_at_k")
            task = engine["by_bucket"].get("task", {}).get("recall_at_k")
            print(
                f"  {name:10s} recall@{num_results} = {engine['recall_at_k']:.4f}  "
                f"MRR = {fmt_or_na(engine['mrr_at_k'], 4)}  "
                f"(title = {fmt_or_na(title, 3)}, task = {fmt_or_na(task, 3)}; "
                f"{engine['num_scored']}/{report['num_queries']} scored; "
                f"{engine['search_errors']} search errs; "
                f"misses: {engine['misses_system_specific']} sys / "
                f"{engine['misses_universal']} univ)",
                file=sys.stderr,
            )
