import asyncio
import json
import sys
from collections import Counter
from datetime import UTC, datetime

from keenbench.finance.canon import FIELD_TYPES
from keenbench.finance.generate import GenStats, run_generate
from keenbench.finance.models import QUARTERLY_FIELDS
from keenbench.finance.registries import GleifClient, SecClient, WikidataClient
from keenbench.finance.score import GoldQuery, run_answers
from keenbench.finance.sources import EdgarClient
from keenbench.shared.cli import (
    aclose_all,
    as_obj,
    build_clients_or_exit,
    current_hour,
    load_gold_rows,
    parse_csv,
    parse_known_csv,
    require_openrouter_client,
    resolve_seed,
    sample_or_exit,
)
from keenbench.shared.io import write_json, write_jsonl
from keenbench.shared.llm import resolve_judge_model, resolve_llm_model

KNOWN_SUITES = ("finance", "filings", "filingdoc")


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


class Finance:
    def generate(
        self,
        suites: str | tuple[str, ...] = "finance,filings,filingdoc",
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
        suite_names = parse_known_csv(suites, KNOWN_SUITES, flag="--suites")
        field_names = (
            parse_known_csv(fields, QUARTERLY_FIELDS, flag="--fields")
            if "filings" in suite_names
            else tuple(parse_csv(fields))
        )
        if min_employee_year <= 0:
            min_employee_year = datetime.now(UTC).year - 1
        now, hour_ts = current_hour()
        seed = resolve_seed(seed, hour_ts)

        concurrency = max(1, registry_concurrency)
        sec = SecClient(max_concurrency=concurrency)
        wikidata = WikidataClient(max_concurrency=concurrency) if "finance" in suite_names else None
        gleif = (
            GleifClient(max_concurrency=concurrency)
            if use_gleif and "finance" in suite_names
            else None
        )
        edgar = EdgarClient(max_concurrency=concurrency) if "filingdoc" in suite_names else None
        llm = None
        if "filingdoc" in suite_names:
            llm = require_openrouter_client(
                resolve_llm_model(llm_model), purpose="the filingdoc suite"
            )

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
                    seed=seed,
                    doc_concurrency=doc_concurrency,
                )
            finally:
                await aclose_all(sec, wikidata, gleif, edgar, llm)

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
            f"finance: {stats.rows} queries from {stats.companies} companies "
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
        snippet_chars: int = 2000,
        limit: int = 0,
        sample: str = "stratified",
        seed: int | None = None,
        judge: bool = False,
        judge_model: str | None = None,
        judge_concurrency: int = 8,
    ) -> None:
        rows = load_gold_rows(queries, bench="finance", gold_ok=_gold_ok)
        rows = sample_or_exit(
            rows,
            limit,
            seed,
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
            model = resolve_judge_model(judge_model)
            judge_llm = require_openrouter_client(model, purpose="--judge")

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
                await aclose_all(*clients.values(), judge_llm)

        report = asyncio.run(_go())
        if model is not None:
            report["judge_model"] = model
        write_json(report, out)

        judged = f", judge={model}" if model else ""
        print(
            f"\nfinance: {report['num_queries']} queries, top-{num_results}{judged}",
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
