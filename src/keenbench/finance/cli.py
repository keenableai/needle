import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from keenbench.companyfill.canon import FIELD_TYPES
from keenbench.companyfill.registries import SecClient
from keenbench.finance.generate import GenStats, run_generate, tiered_companies
from keenbench.finance.models import QUARTERLY_FIELDS, SUITES, serialize_row
from keenbench.finance.score import GoldFinance, run_finance
from keenbench.finance.sources import EdgarClient
from keenbench.shared.cli import build_clients_or_exit, parse_csv, sample_or_exit
from keenbench.shared.io import write_json, write_jsonl
from keenbench.shared.llm import OpenRouterClient, resolve_llm_model


def _as_obj(value: object) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _load_gold_rows(path: str) -> list[dict]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SystemExit(f"error: could not read --queries {path!r}: {exc}") from exc
    rows = []
    malformed = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        obj = _as_obj(line)
        if not isinstance(obj, dict) or not obj.get("query_text"):
            continue
        gold = _as_obj(obj.get("gold"))
        if not isinstance(gold, dict):
            malformed += 1
            continue
        has_answer = gold.get("field") and gold.get("field_type")
        has_item = isinstance(gold.get("ids"), dict) and gold["ids"].get("adsh")
        if not has_answer and not has_item:
            malformed += 1
            continue
        if has_answer and str(gold["field_type"]) not in FIELD_TYPES:
            malformed += 1
            continue
        obj["gold"] = gold
        origin = _as_obj(obj.get("query_origin"))
        obj["query_origin"] = origin if isinstance(origin, dict) else {}
        rows.append(obj)
    if malformed:
        print(f"finance: skipped {malformed} malformed gold rows", file=sys.stderr)
    return rows


def _gold_finance(row: dict) -> GoldFinance:
    gold = row["gold"]
    origin = row.get("query_origin") or {}
    ids = gold.get("ids") or {}
    kind = "item" if ids.get("adsh") else "answer"
    return GoldFinance(
        text=str(row["query_text"]),
        kind=kind,
        bucket=str(origin.get("bucket") or "unknown"),
        syntax=str(origin.get("syntax") or "plain"),
        field=str(gold.get("field") or ""),
        field_type=str(gold.get("field_type") or ""),
        value=gold.get("value"),
        aliases=tuple(str(a) for a in gold.get("aliases") or []),
        age_bucket=str(gold.get("age_bucket") or ""),
        adsh=str(ids.get("adsh") or ""),
        form=str(gold.get("form") or ""),
        tier=str(gold.get("tier") or ""),
    )


class Finance:
    def generate(
        self,
        out: str = "-",
        suites: str | tuple[str, ...] = "filings,filingdoc",
        fields: str | tuple[str, ...] = "net_income,operating_income,eps_diluted",
        max_companies: int = 200,
        per_company: int = 2,
        quarters_back: int = 6,
        filingdoc_target: int = 40,
        seed: int = 0,
        llm_model: str | None = None,
        doc_concurrency: int = 8,
        registry_concurrency: int = 4,
    ) -> None:
        suite_names = tuple(parse_csv(suites))
        unknown = [s for s in suite_names if s not in SUITES]
        if unknown or not suite_names:
            raise SystemExit(
                f"error: unknown --suites {','.join(unknown) or suites!r} "
                f"(known: {', '.join(SUITES)})"
            )
        field_names = tuple(parse_csv(fields))
        bad_fields = [f for f in field_names if f not in QUARTERLY_FIELDS]
        if bad_fields or not field_names:
            raise SystemExit(
                f"error: unknown --fields {','.join(bad_fields) or fields!r} "
                f"(known: {', '.join(QUARTERLY_FIELDS)})"
            )

        now = datetime.now(UTC)
        hour_ts = now.replace(minute=0, second=0, microsecond=0)

        concurrency = max(1, registry_concurrency)
        sec = SecClient(max_concurrency=concurrency)
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
                seed_rows = tiered_companies(all_rows, max(1, max_companies // 3), seed)
                return await run_generate(
                    sec=sec if "filings" in suite_names else None,
                    edgar=edgar,
                    llm=llm,
                    seed_rows=seed_rows,
                    hour_ts=hour_ts,
                    now=now,
                    fields=field_names,
                    per_company=per_company,
                    quarters_back=quarters_back,
                    filingdoc_target=filingdoc_target,
                    seed=seed,
                    doc_concurrency=doc_concurrency,
                )
            finally:
                for client in (sec, edgar, llm):
                    if client is not None:
                        await client.aclose()

        rows, stats = asyncio.run(_go())
        write_jsonl([serialize_row(r) for r in rows], out)
        print(
            f"finance: {stats.filings_rows + stats.filingdoc_rows} queries from "
            f"{stats.companies} companies (filings={stats.filings_rows}, "
            f"facts_missing={stats.facts_missing}; filingdoc={stats.filingdoc_rows} of "
            f"{stats.doc_candidates} candidates, drops: fetch={stats.doc_fetch_fail}, "
            f"thin={stats.doc_thin}, no_query={stats.doc_no_query}, "
            f"rejected={stats.doc_rejected}, llm_err={stats.llm_errors}; "
            f"errors={stats.errors})",
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
        seed: int = 0,
    ) -> None:
        rows = _load_gold_rows(queries)
        if not rows:
            raise SystemExit(f"error: no gold query rows loaded from {queries!r}")
        rows = sample_or_exit(
            rows,
            limit,
            seed,
            strategy=sample,
            key=lambda r: (
                f"{r['query_origin'].get('bucket', '?')}:{r['query_origin'].get('syntax', '?')}"
            ),
        )
        gold_rows = [_gold_finance(r) for r in rows]

        clients = build_clients_or_exit(engines, snippet_chars=snippet_chars)

        async def _go() -> dict:
            try:
                return await run_finance(
                    gold_rows,
                    clients,
                    num_results=num_results,
                    snippet_chars=snippet_chars,
                )
            finally:
                for c in clients.values():
                    await c.aclose()

        report = asyncio.run(_go())
        write_json(report, out)

        print(
            f"\nfinance: {report['num_queries']} queries, top-{num_results}",
            file=sys.stderr,
        )
        for name, e in report["engines"].items():
            filings = e["by_bucket"].get("filings", {}).get("recall_at_k")
            filingdoc = e["by_bucket"].get("filingdoc", {}).get("recall_at_k")
            filings_str = f"{filings:.3f}" if filings is not None else "n/a"
            filingdoc_str = f"{filingdoc:.3f}" if filingdoc is not None else "n/a"
            print(
                f"  {name:10s} recall@{num_results} = {e['recall_at_k']:.4f}  "
                f"MRR = {e['mrr_at_k']:.4f}  "
                f"(filings = {filings_str}, filingdoc = {filingdoc_str}; "
                f"{e['num_scored']}/{report['num_queries']} scored; "
                f"{e['search_errors']} search errs; "
                f"misses: {e['misses_system_specific']} sys / {e['misses_universal']} univ)",
                file=sys.stderr,
            )
