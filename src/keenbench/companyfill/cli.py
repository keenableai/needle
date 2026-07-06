import asyncio
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime

from keenbench.companyfill.canon import FIELD_TYPES
from keenbench.companyfill.generate import GenStats, run_generate
from keenbench.companyfill.models import QUARTERLY_FIELDS
from keenbench.companyfill.registries import GleifClient, SecClient, WikidataClient
from keenbench.companyfill.score import GoldQuery, run_answers
from keenbench.companyfill.sources import EdgarClient
from keenbench.shared.cli import (
    as_obj,
    build_clients_or_exit,
    load_gold_rows,
    parse_csv,
    sample_or_exit,
)
from keenbench.shared.io import write_json, write_jsonl
from keenbench.shared.llm import OpenRouterClient, resolve_judge_model, resolve_llm_model
from keenbench.shared.sampling import resolve_seed

KNOWN_SUITES = ("companyfill", "filings", "filingdoc")


def _gold_ok(gold: dict) -> bool:
    if not gold.get("field") or not gold.get("field_type"):
        return False
    field_type = str(gold["field_type"])
    if field_type not in FIELD_TYPES:
        raise SystemExit(
            f"error: unsupported gold.field_type {field_type!r} "
            f"(known: {', '.join(sorted(FIELD_TYPES))})"
        )
    return True


def _gold_query(row: dict) -> GoldQuery:
    origin = as_obj(row.get("query_origin"))
    origin = origin if isinstance(origin, dict) else {}
    gold = row["gold"]
    return GoldQuery(
        text=str(row["query_text"]),
        field=str(gold["field"]),
        field_type=str(gold["field_type"]),
        value=gold.get("value"),
        aliases=tuple(str(a) for a in gold.get("aliases") or []),
        bucket=str(origin.get("bucket") or "unknown"),
        freshness_window=str(gold.get("freshness_window") or "static"),
        syntax=str(origin.get("syntax") or "plain"),
        tier=str(gold.get("tier") or ""),
    )


class Companyfill:
    def generate(
        self,
        suites: str | tuple[str, ...] = "companyfill,filings,filingdoc",
        out: str = "-",
        max_companies: int = 100,
        use_gleif: bool = False,
        min_employee_year: int = 0,
        fields: str | tuple[str, ...] = "net_income,operating_income,eps_diluted",
        per_company: int = 2,
        quarters_back: int = 6,
        filingdoc_target: int = 40,
        seed: int | None = None,
        llm_model: str | None = None,
        doc_concurrency: int = 8,
        registry_concurrency: int = 4,
    ) -> None:
        suite_names = tuple(parse_csv(suites))
        unknown = [s for s in suite_names if s not in KNOWN_SUITES]
        if unknown or not suite_names:
            raise SystemExit(
                f"error: unknown --suites {','.join(unknown) or suites!r} "
                f"(known: {', '.join(KNOWN_SUITES)})"
            )
        field_names = tuple(parse_csv(fields))
        bad_fields = [f for f in field_names if f not in QUARTERLY_FIELDS]
        if "filings" in suite_names and (bad_fields or not field_names):
            raise SystemExit(
                f"error: unknown --fields {','.join(bad_fields) or fields!r} "
                f"(known: {', '.join(QUARTERLY_FIELDS)})"
            )
        if min_employee_year <= 0:
            min_employee_year = datetime.now(UTC).year - 1
        now = datetime.now(UTC)
        hour_ts = now.replace(minute=0, second=0, microsecond=0)

        concurrency = max(1, registry_concurrency)
        sec = SecClient(max_concurrency=concurrency)
        wikidata = (
            WikidataClient(max_concurrency=concurrency) if "companyfill" in suite_names else None
        )
        gleif = (
            GleifClient(max_concurrency=concurrency)
            if use_gleif and "companyfill" in suite_names
            else None
        )
        edgar = EdgarClient(max_concurrency=concurrency) if "filingdoc" in suite_names else None
        llm = None
        if "filingdoc" in suite_names:
            key = os.environ.get("OPENROUTER_API_KEY")
            if not key:
                raise SystemExit(
                    "error: OPENROUTER_API_KEY is not set (needed for the filingdoc suite)"
                )
            llm = OpenRouterClient(api_key=key, model=resolve_llm_model(llm_model))

        async def _go() -> tuple[list[dict], GenStats]:
            try:
                all_rows = await sec.tickers(0)
                if not all_rows:
                    raise SystemExit("error: could not load the SEC company_tickers seed")
                return await run_generate(
                    all_rows,
                    wikidata=wikidata,
                    sec=sec if "filings" in suite_names else None,
                    gleif=gleif,
                    edgar=edgar,
                    llm=llm,
                    suites=suite_names,
                    hour_ts=hour_ts,
                    now=now,
                    min_employee_year=min_employee_year,
                    max_companies=max_companies,
                    fields=field_names,
                    per_company=per_company,
                    quarters_back=quarters_back,
                    filingdoc_target=filingdoc_target,
                    seed=resolve_seed(seed, hour_ts),
                    doc_concurrency=doc_concurrency,
                )
            finally:
                for client in (sec, wikidata, gleif, edgar, llm):
                    if client is not None:
                        await client.aclose()

        try:
            rows, stats = asyncio.run(_go())
        except ValueError as exc:
            raise SystemExit(f"error: {exc}") from exc
        records = []
        for row in rows:
            record = dict(row)
            record["query_origin"] = json.dumps(record["query_origin"], sort_keys=True)
            records.append(record)
        write_jsonl(records, out)

        by_bucket = Counter(row["query_origin"]["bucket"] for row in rows)
        buckets = ", ".join(f"{b}={n}" for b, n in sorted(by_bucket.items())) or "none"
        print(
            f"companyfill: {stats.rows} queries from {stats.companies} companies "
            f"({buckets}; {stats.resolved} resolved in wikidata; "
            f"filings={stats.filings_rows} (facts_missing={stats.facts_missing}); "
            f"filingdoc={stats.filingdoc_rows} of {stats.doc_candidates} candidates "
            f"(fetch={stats.doc_fetch_fail}, thin={stats.doc_thin}, "
            f"no_query={stats.doc_no_query}, rejected={stats.doc_rejected}, "
            f"surplus={stats.doc_surplus}, llm_err={stats.llm_errors}); "
            f"{stats.errors} errors)",
            file=sys.stderr,
        )

    def run(
        self,
        queries: str,
        out: str = "-",
        engines: str | tuple[str, ...] = "keenable,exa",
        num_results: int = 5,
        snippet_chars: int = 500,
        limit: int = 0,
        sample: str = "stratified",
        seed: int | None = None,
        judge: bool = False,
        judge_model: str | None = None,
        judge_concurrency: int = 8,
    ) -> None:
        rows = load_gold_rows(queries, bench="companyfill", gold_ok=_gold_ok)
        if not rows:
            raise SystemExit(f"error: no gold query rows loaded from {queries!r}")
        rows = sample_or_exit(
            rows,
            limit,
            resolve_seed(seed),
            strategy=sample,
            key=lambda r: (
                f"{r['query_origin'].get('bucket', '?')}:"
                f"{r['query_origin'].get('syntax', '?')}:{r['gold'].get('field', '?')}"
            ),
        )
        gold_queries = [_gold_query(r) for r in rows]

        clients = build_clients_or_exit(engines, snippet_chars=snippet_chars)

        judge_llm = None
        model = None
        if judge:
            openrouter_key = os.environ.get("OPENROUTER_API_KEY")
            if not openrouter_key:
                raise SystemExit("error: OPENROUTER_API_KEY is not set (needed for --judge)")
            model = resolve_judge_model(judge_model)
            judge_llm = OpenRouterClient(api_key=openrouter_key, model=model)

        async def _go() -> dict:
            try:
                return await run_answers(
                    gold_queries,
                    clients,
                    num_results=num_results,
                    snippet_chars=snippet_chars,
                    judge=judge_llm,
                    judge_concurrency=judge_concurrency,
                )
            finally:
                for c in clients.values():
                    await c.aclose()
                if judge_llm is not None:
                    await judge_llm.aclose()

        report = asyncio.run(_go())
        if model is not None:
            report["judge_model"] = model
        write_json(report, out)

        judged = f", judge={model}" if model else ""
        print(
            f"\ncompanyfill: {report['num_queries']} queries, top-{num_results}{judged}",
            file=sys.stderr,
        )
        for name, e in report["engines"].items():
            filings = e["by_bucket"].get("filings", {}).get("recall_at_k")
            filingdoc = e["by_bucket"].get("filingdoc", {}).get("recall_at_k")
            filings_str = f"{filings:.3f}" if filings is not None else "n/a"
            filingdoc_str = f"{filingdoc:.3f}" if filingdoc is not None else "n/a"
            extras = f"{e['search_errors']} search errs"
            if model:
                extras += f"; {e['judge_upgrades']} judge upgrades, {e['judge_errors']} judge errs"
            print(
                f"  {name:10s} answer-recall@{num_results} = {e['recall_at_k']:.4f}  "
                f"MRR = {e['mrr_at_k']:.4f}  "
                f"(filings = {filings_str}, filingdoc = {filingdoc_str}; "
                f"{e['num_scored']}/{report['num_queries']} scored; {extras})",
                file=sys.stderr,
            )
