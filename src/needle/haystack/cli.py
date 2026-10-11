import asyncio
import sys

from needle.finance.registries import SecClient
from needle.finance.score import GoldQuery
from needle.finance.sources import EdgarClient
from needle.haystack.generate import GenStats, run_generate
from needle.haystack.models import HAYSTACK_FIELD_TYPES, SUITES
from needle.haystack.score import run_haystack
from needle.haystack.sources import FederalRegisterClient, WikiClient
from needle.scholar.sources import ArxivClient
from needle.shared.cli import (
    aclose_all,
    as_obj,
    build_clients_or_exit,
    current_hour,
    fmt_or_na,
    load_gold_rows,
    parse_known_csv,
    require_openrouter_client,
    resolve_seed,
    sample_or_exit,
)
from needle.shared.io import serialize_row, write_json, write_jsonl
from needle.shared.llm import resolve_judge_model, resolve_llm_model
from needle.shared.search import DEFAULT_SNIPPET_CHARS


def _gold_ok(gold: dict) -> bool:
    if not gold.get("field_type") or gold.get("value") in (None, ""):
        return False
    field_type = str(gold["field_type"])
    if field_type not in HAYSTACK_FIELD_TYPES:
        raise SystemExit(
            f"error: unsupported gold.field_type {field_type!r} "
            f"(known: {', '.join(sorted(HAYSTACK_FIELD_TYPES))})"
        )
    return True


def _gold_query(row: dict) -> GoldQuery:
    origin = as_obj(row.get("query_origin"))
    origin = origin if isinstance(origin, dict) else {}
    provenance = origin.get("provenance") or {}
    gold = row["gold"]
    return GoldQuery(
        text=str(row["query_text"]),
        field=str(gold["field_type"]),
        field_type=str(gold["field_type"]),
        value=gold.get("value"),
        aliases=tuple(str(a) for a in gold.get("aliases") or []),
        bucket=str(origin.get("bucket") or "unknown"),
        freshness_window=str(gold.get("freshness_window") or "static"),
        syntax=str(origin.get("syntax") or "plain"),
        extras=(("depth_pct", int(provenance.get("depth_pct") or 0)),),
    )


class Haystack:
    def generate(
        self,
        suites: str | tuple[str, ...] = "gov,sec,wiki,arxiv",
        out: str = "-",
        per_suite: int = 15,
        oversample: int = 3,
        seed: int | None = None,
        llm_model: str | None = None,
        doc_concurrency: int = 8,
        source_concurrency: int = 4,
    ) -> None:
        suite_names = parse_known_csv(suites, SUITES, flag="--suites")
        now, hour_ts = current_hour()
        seed = resolve_seed(seed, hour_ts)
        llm = require_openrouter_client(
            resolve_llm_model(llm_model), purpose="haystack question generation"
        )

        concurrency = max(1, source_concurrency)
        fr = FederalRegisterClient(max_concurrency=concurrency) if "gov" in suite_names else None
        sec = SecClient(max_concurrency=concurrency) if "sec" in suite_names else None
        edgar = EdgarClient(max_concurrency=concurrency) if "sec" in suite_names else None
        wiki = WikiClient(max_concurrency=concurrency) if "wiki" in suite_names else None
        arxiv = ArxivClient(max_concurrency=1) if "arxiv" in suite_names else None

        async def _go() -> tuple[list[dict], GenStats]:
            try:
                return await run_generate(
                    fr=fr,
                    wiki=wiki,
                    sec=sec,
                    edgar=edgar,
                    arxiv=arxiv,
                    llm=llm,
                    suites=suite_names,
                    hour_ts=hour_ts,
                    now=now,
                    per_suite=per_suite,
                    oversample=oversample,
                    seed=seed,
                    doc_concurrency=doc_concurrency,
                )
            finally:
                await aclose_all(fr, sec, edgar, wiki, arxiv, llm)

        rows, stats = asyncio.run(_go())
        write_jsonl([serialize_row(r, fields=("query_origin",)) for r in rows], out)

        suites_str = ", ".join(f"{s}={n}" for s, n in sorted(stats.by_suite.items())) or "none"
        print(
            f"haystack: {stats.rows} queries of {stats.candidates} candidates ({suites_str}; "
            f"fetch={stats.fetch_fail}, thin={stats.thin}, no_question={stats.no_question}, "
            f"rejected={stats.rejected}, surplus={stats.surplus}, llm_err={stats.llm_errors})",
            file=sys.stderr,
        )

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
        judge: bool = False,
        judge_model: str | None = None,
        judge_concurrency: int = 8,
    ) -> None:
        rows = load_gold_rows(queries, bench="haystack", gold_ok=_gold_ok)
        rows = sample_or_exit(
            rows,
            limit,
            seed,
            strategy=sample,
            key=lambda r: (
                f"{r['query_origin'].get('bucket', '?')}:"
                f"{r['query_origin'].get('syntax', '?')}:{r['gold'].get('field_type', '?')}"
            ),
        )
        gold_queries = [_gold_query(r) for r in rows]

        clients = build_clients_or_exit(engines, snippet_chars=snippet_chars)

        judge_llm = None
        model = None
        if judge:
            model = resolve_judge_model(judge_model)
            judge_llm = require_openrouter_client(model, purpose="--judge")

        async def _go() -> dict:
            try:
                return await run_haystack(
                    gold_queries,
                    clients,
                    num_results=num_results,
                    snippet_chars=snippet_chars,
                    judge=judge_llm,
                    judge_concurrency=judge_concurrency,
                )
            finally:
                await aclose_all(*clients.values(), judge_llm)

        report = asyncio.run(_go())
        if model is not None:
            report["judge_model"] = model
        write_json(report, out)

        judged = f", judge={model}" if model else ""
        print(
            f"\nhaystack: {report['num_queries']} queries, top-{num_results}{judged}",
            file=sys.stderr,
        )
        for name, e in report["engines"].items():
            suites_str = ", ".join(
                f"{s} = {fmt_or_na(e['by_bucket'].get(s, {}).get('recall_at_k'), 3)}"
                for s in SUITES
                if s in e["by_bucket"]
            )
            extras = f"{e['search_errors']} search errs"
            if model:
                extras += f"; {e['judge_upgrades']} judge upgrades, {e['judge_errors']} judge errs"
            print(
                f"  {name:10s} answer-recall@{num_results} = {e['recall_at_k']:.4f}  "
                f"MRR = {fmt_or_na(e['mrr_at_k'], 4)}  "
                f"({suites_str}; {e['num_scored']}/{report['num_queries']} scored; {extras})",
                file=sys.stderr,
            )
