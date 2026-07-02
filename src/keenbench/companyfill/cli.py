import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from keenbench.companyfill.generate import GenStats, run_generate
from keenbench.companyfill.judge import DEFAULT_JUDGE_MODEL
from keenbench.companyfill.registries import GleifClient, SecClient, WikidataClient
from keenbench.companyfill.score import GoldQuery, run_answers
from keenbench.shared.io import write_jsonl, write_stdout
from keenbench.shared.llm import OpenRouterClient
from keenbench.shared.sampling import sample_stratified, sample_uniform
from keenbench.shared.search import ExaClient, KeenableClient, SearchClient

KNOWN_SUITES = ("companyfill", "financials")


def _parse_csv(value: str | tuple[str, ...]) -> list[str]:
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(v).strip() for v in value]


def _load_gold_rows(path: str) -> list[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or not obj.get("query_text"):
            continue
        gold = obj.get("gold")
        if not isinstance(gold, dict) or not gold.get("field") or not gold.get("field_type"):
            continue
        rows.append(obj)
    return rows


def _gold_query(row: dict) -> GoldQuery:
    origin = row.get("query_origin")
    if isinstance(origin, str):
        try:
            origin = json.loads(origin)
        except json.JSONDecodeError:
            origin = {}
    gold = row["gold"]
    return GoldQuery(
        text=str(row["query_text"]),
        field=str(gold["field"]),
        field_type=str(gold["field_type"]),
        value=gold.get("value"),
        aliases=tuple(str(a) for a in gold.get("aliases") or []),
        bucket=str((origin or {}).get("bucket") or "unknown"),
        freshness_window=str(gold.get("freshness_window") or "static"),
    )


class Companyfill:
    def generate(
        self,
        out: str = "-",
        suites: str | tuple[str, ...] = "companyfill,financials",
        limit: int = 100,
        use_gleif: bool = False,
        min_employee_year: int = 0,
        registry_concurrency: int = 4,
    ) -> None:
        suite_names = tuple(_parse_csv(suites))
        unknown = [s for s in suite_names if s not in KNOWN_SUITES]
        if unknown or not suite_names:
            raise SystemExit(
                f"error: unknown --suites {','.join(unknown) or suites!r} "
                f"(known: {', '.join(KNOWN_SUITES)})"
            )
        if min_employee_year <= 0:
            min_employee_year = datetime.now(UTC).year - 1
        hour_ts = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)

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

        async def _go() -> tuple[list[dict], GenStats]:
            try:
                seed = await sec.tickers(limit)
                if not seed:
                    raise SystemExit("error: could not load the SEC company_tickers seed")
                return await run_generate(
                    seed,
                    wikidata=wikidata,
                    sec=sec if "financials" in suite_names else None,
                    gleif=gleif,
                    suites=suite_names,
                    hour_ts=hour_ts,
                    min_employee_year=min_employee_year,
                )
            finally:
                for client in (sec, wikidata, gleif):
                    if client is not None:
                        await client.aclose()

        rows, stats = asyncio.run(_go())
        records = []
        for row in rows:
            record = dict(row)
            record["query_origin"] = json.dumps(record["query_origin"], sort_keys=True)
            records.append(record)
        if out == "-":
            write_stdout(records)
        else:
            write_jsonl(records, out)

        by_bucket: dict[str, int] = {}
        for row in rows:
            by_bucket[row["query_origin"]["bucket"]] = (
                by_bucket.get(row["query_origin"]["bucket"], 0) + 1
            )
        buckets = ", ".join(f"{b}={n}" for b, n in sorted(by_bucket.items())) or "none"
        print(
            f"companyfill: {stats.rows} queries from {stats.companies} companies "
            f"({buckets}; {stats.resolved} resolved in wikidata, {stats.errors} errors)",
            file=sys.stderr,
        )

    def run(
        self,
        queries: str,
        out: str = "-",
        engines: str | tuple[str, ...] = "keenable,exa",
        num_results: int = 5,
        snippet_chars: int = 500,
        keenable_mode: str = "pro",
        exa_concurrency: int = 4,
        limit: int = 0,
        sample: str = "stratified",
        seed: int = 0,
        judge: bool = False,
        judge_model: str | None = None,
        judge_concurrency: int = 8,
    ) -> None:
        rows = _load_gold_rows(queries)
        if not rows:
            raise SystemExit(f"error: no gold query rows loaded from {queries!r}")
        if limit > 0 and len(rows) > limit:
            if sample == "stratified":
                tagged = [dict(r, _strat=r["gold"]["field"]) for r in rows]
                rows = [dict(r) for r in sample_stratified(tagged, limit, seed, key="_strat")]
                for r in rows:
                    r.pop("_strat", None)
            elif sample == "uniform":
                rows = sample_uniform(rows, limit, seed)
            elif sample == "head":
                rows = rows[:limit]
            else:
                raise SystemExit(
                    f"error: --sample: unknown sample strategy {sample!r} "
                    "(known: stratified, uniform, head)"
                )
        gold_queries = [_gold_query(r) for r in rows]

        engine_names = _parse_csv(engines)
        clients: dict[str, SearchClient] = {}
        for name in engine_names:
            if name == "keenable":
                clients[name] = KeenableClient(
                    api_key=os.environ.get("KEENABLE_API_KEY"), mode=keenable_mode
                )
            elif name == "exa":
                exa_key = os.environ.get("EXA_API_KEY")
                if not exa_key:
                    raise SystemExit("error: EXA_API_KEY is not set (needed for the exa engine)")
                clients[name] = ExaClient(
                    api_key=exa_key,
                    max_concurrency=exa_concurrency,
                    highlight_chars=snippet_chars,
                )
            else:
                raise SystemExit(f"error: unknown engine {name!r} (known: keenable, exa)")
        if not clients:
            raise SystemExit("error: no engines selected")

        judge_llm = None
        model = None
        if judge:
            openrouter_key = os.environ.get("OPENROUTER_API_KEY")
            if not openrouter_key:
                raise SystemExit("error: OPENROUTER_API_KEY is not set (needed for --judge)")
            model = judge_model or os.environ.get("KEENBENCH_JUDGE_MODEL") or DEFAULT_JUDGE_MODEL
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

        text = json.dumps(report, ensure_ascii=False, indent=2)
        if out == "-":
            print(text)
        else:
            Path(out).write_text(text + "\n", encoding="utf-8")

        judged = f", judge={model}" if model else ""
        print(
            f"\ncompanyfill: {report['num_queries']} queries, top-{num_results}{judged}",
            file=sys.stderr,
        )
        for name, e in report["engines"].items():
            extras = f"{e['search_errors']} search errs"
            if model:
                extras += f"; {e['judge_upgrades']} judge upgrades, {e['judge_errors']} judge errs"
            print(
                f"  {name:10s} answer-recall@{num_results} = {e['recall_at_k']:.4f}  "
                f"MRR = {e['mrr_at_k']:.4f}  "
                f"({e['num_scored']}/{report['num_queries']} scored; {extras})",
                file=sys.stderr,
            )
