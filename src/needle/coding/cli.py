import asyncio
import sys

from needle.coding.generate import GenStats, run_generate
from needle.coding.models import DOC_TYPES
from needle.coding.score import GoldDoc, run_coding
from needle.coding.sources import ApiDocsClient, GitHubClient, StackExchangeClient
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

DEFAULT_REPOS = (
    "pandas-dev/pandas,numpy/numpy,pytorch/pytorch,huggingface/transformers,"
    "scikit-learn/scikit-learn,pydantic/pydantic,astral-sh/uv,microsoft/TypeScript,"
    "vercel/next.js,vitejs/vite,nodejs/node,facebook/react,rust-lang/rust,tokio-rs/tokio,"
    "golang/go"
)
DEFAULT_TAGS = "python,javascript,typescript,rust,go,java"


def _gold_doc(row: dict) -> GoldDoc:
    origin = row.get("query_origin") or {}
    return GoldDoc(
        text=str(row["query_text"]),
        doc_key=str(row["gold"].get("doc_key") or ""),
        bucket=str(origin.get("bucket") or "unknown"),
        syntax=str(origin.get("syntax") or "plain"),
    )


class Coding:
    def generate(
        self,
        out: str = "-",
        types: str | tuple[str, ...] = "api,issue,qa",
        per_type: int = 20,
        repos: str | tuple[str, ...] = DEFAULT_REPOS,
        tags: str | tuple[str, ...] = DEFAULT_TAGS,
        months_back: int = 12,
        seed: int | None = None,
        llm_model: str | None = None,
        concurrency: int = 8,
    ) -> None:
        type_names = parse_known_csv(types, DOC_TYPES, flag="--types")
        now, hour_ts = current_hour()
        seed = resolve_seed(seed, hour_ts)
        llm = require_openrouter_client(resolve_llm_model(llm_model), purpose="coding queries")
        api = ApiDocsClient() if "api" in type_names else None
        github = GitHubClient() if "issue" in type_names else None
        stackexchange = StackExchangeClient() if "qa" in type_names else None

        async def _go() -> tuple[list[dict], GenStats]:
            try:
                return await run_generate(
                    api=api,
                    github=github,
                    stackexchange=stackexchange,
                    llm=llm,
                    hour_ts=hour_ts,
                    now=now,
                    per_type=per_type,
                    repos=tuple(parse_csv(repos)),
                    tags=tuple(parse_csv(tags)),
                    months_back=months_back,
                    seed=seed,
                    concurrency=concurrency,
                )
            finally:
                await aclose_all(api, github, stackexchange, llm)

        rows, stats = asyncio.run(_go())
        counts = ", ".join(
            f"{t}={stats.rows.get(t, 0)} of {stats.candidates.get(t, 0)}" for t in type_names
        )
        print(
            f"coding: {len(rows)} queries ({counts}; drops: no_query={stats.no_query}, "
            f"rejected={stats.rejected}, llm_err={stats.llm_errors})",
            file=sys.stderr,
        )
        if stats.llm_error_sample:
            print(f"coding first llm error: {stats.llm_error_sample}", file=sys.stderr)
        for err in stats.source_errors:
            print(f"coding source error: {err}", file=sys.stderr)
        empty = [t for t in type_names if not stats.rows.get(t)]
        if empty:
            raise SystemExit(f"error: no {','.join(empty)} queries; not writing a partial set")
        write_jsonl([serialize_row(r) for r in rows], out)

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
                f"{r['query_origin'].get('bucket', '?')}:{r['query_origin'].get('syntax', '?')}"
            ),
        )
        gold_rows = [_gold_doc(r) for r in rows]
        clients = build_clients_or_exit(engines, snippet_chars=snippet_chars)

        async def _go() -> dict:
            try:
                return await run_coding(
                    gold_rows, clients, num_results=num_results, snippet_chars=snippet_chars
                )
            finally:
                await aclose_all(*clients.values())

        report = asyncio.run(_go())
        write_json(report, out)

        print(f"\ncoding: {report['num_queries']} queries, top-{num_results}", file=sys.stderr)
        for name, e in report["engines"].items():
            buckets = ", ".join(
                f"{t} = {fmt_or_na(e['by_bucket'].get(t, {}).get('recall_at_k'), 3)}"
                for t in DOC_TYPES
            )
            print(
                f"  {name:10s} recall@{num_results} = {e['recall_at_k']:.4f}  "
                f"MRR = {fmt_or_na(e['mrr_at_k'], 4)}  ({buckets}; "
                f"{e['num_scored']}/{report['num_queries']} scored; "
                f"{e['search_errors']} search errs; "
                f"misses: {e['misses_system_specific']} sys / {e['misses_universal']} univ)",
                file=sys.stderr,
            )
