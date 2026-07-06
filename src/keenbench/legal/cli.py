import asyncio
import os
import sys
from datetime import UTC, datetime

from keenbench.legal.generate import GenStats, run_generate
from keenbench.legal.models import SUITES, serialize_row
from keenbench.legal.score import GoldLegal, run_legal
from keenbench.legal.sources import CourtListenerClient, EcfrClient
from keenbench.shared.cli import (
    build_clients_or_exit,
    load_gold_rows,
    parse_csv,
    sample_or_exit,
)
from keenbench.shared.io import write_json, write_jsonl
from keenbench.shared.llm import OpenRouterClient, resolve_llm_model

DEFAULT_COURTS = "scotus,ca1,ca2,ca3,ca4,ca5,ca6,ca7,ca8,ca9,ca10,ca11,cadc,cafc"
DEFAULT_TITLES = "7,12,14,17,21,26,29,40,47,49"


def _gold_ok(gold: dict) -> bool:
    ids = gold.get("ids")
    return isinstance(ids, dict) and bool(ids)


def _gold_legal(row: dict) -> GoldLegal:
    gold = row["gold"]
    origin = row.get("query_origin") or {}
    ids = gold.get("ids") or {}
    return GoldLegal(
        text=str(row["query_text"]),
        case_key=str(gold.get("case_key") or ""),
        bucket=str(origin.get("bucket") or "unknown"),
        syntax=str(origin.get("syntax") or "plain"),
        cluster=str(ids.get("cluster") or ""),
        docket=str(ids.get("docket") or ""),
        cites=tuple(str(c) for c in ids.get("cites") or []),
        cfr=str(ids.get("cfr") or ""),
        party_tokens=tuple(str(t) for t in gold.get("party_tokens") or []),
        court=str(gold.get("court") or ""),
    )


class Legal:
    def generate(
        self,
        out: str = "-",
        suites: str | tuple[str, ...] = "caselaw,code",
        courts: str | tuple[str, ...] = DEFAULT_COURTS,
        per_court: int = 4,
        months_back: int = 18,
        titles: str | tuple[str, ...] = DEFAULT_TITLES,
        per_title: int = 6,
        seed: int = 0,
        llm_model: str | None = None,
        code_concurrency: int = 8,
    ) -> None:
        suite_names = tuple(parse_csv(suites))
        unknown = [s for s in suite_names if s not in SUITES]
        if unknown or not suite_names:
            raise SystemExit(
                f"error: unknown --suites {','.join(unknown) or suites!r} "
                f"(known: {', '.join(SUITES)})"
            )
        try:
            title_nums = tuple(int(t) for t in parse_csv(titles))
        except ValueError:
            raise SystemExit(f"error: --titles must be CFR title numbers, got {titles!r}") from None

        now = datetime.now(UTC)
        hour_ts = now.replace(minute=0, second=0, microsecond=0)

        courtlistener = CourtListenerClient() if "caselaw" in suite_names else None
        ecfr = EcfrClient() if "code" in suite_names else None
        llm = None
        if "code" in suite_names:
            key = os.environ.get("OPENROUTER_API_KEY")
            if not key:
                raise SystemExit("error: OPENROUTER_API_KEY is not set (needed for the code suite)")
            llm = OpenRouterClient(api_key=key, model=resolve_llm_model(llm_model))

        async def _go() -> tuple[list[dict], GenStats]:
            try:
                return await run_generate(
                    courtlistener=courtlistener,
                    ecfr=ecfr,
                    llm=llm,
                    hour_ts=hour_ts,
                    now=now,
                    courts=tuple(parse_csv(courts)),
                    per_court=per_court,
                    months_back=months_back,
                    titles=title_nums,
                    per_title=per_title,
                    seed=seed,
                    code_concurrency=code_concurrency,
                )
            finally:
                for client in (courtlistener, ecfr, llm):
                    if client is not None:
                        await client.aclose()

        rows, stats = asyncio.run(_go())
        write_jsonl([serialize_row(r) for r in rows], out)
        print(
            f"legal: {stats.caselaw_rows + stats.code_rows} queries "
            f"(caselaw={stats.caselaw_rows} of {stats.case_candidates} candidates, "
            f"generic_caption={stats.generic_caption}, short_courts={stats.short_courts}; "
            f"code={stats.code_rows} of {stats.section_candidates} sections, "
            f"drops: fetch={stats.section_fetch_fail}, no_query={stats.code_no_query}, "
            f"rejected={stats.code_rejected}, llm_err={stats.llm_errors}, "
            f"short_titles={stats.short_titles})",
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
        rows = load_gold_rows(queries, bench="legal", gold_ok=_gold_ok)
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
        gold_rows = [_gold_legal(r) for r in rows]

        clients = build_clients_or_exit(engines, snippet_chars=snippet_chars)

        async def _go() -> dict:
            try:
                return await run_legal(
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
            f"\nlegal: {report['num_queries']} queries, top-{num_results}",
            file=sys.stderr,
        )
        for name, e in report["engines"].items():
            caselaw = e["by_bucket"].get("caselaw", {}).get("recall_at_k")
            code = e["by_bucket"].get("code", {}).get("recall_at_k")
            caselaw_str = f"{caselaw:.3f}" if caselaw is not None else "n/a"
            code_str = f"{code:.3f}" if code is not None else "n/a"
            print(
                f"  {name:10s} recall@{num_results} = {e['recall_at_k']:.4f}  "
                f"MRR = {e['mrr_at_k']:.4f}  "
                f"(caselaw = {caselaw_str}, code = {code_str}; "
                f"{e['num_scored']}/{report['num_queries']} scored; "
                f"{e['search_errors']} search errs; "
                f"misses: {e['misses_system_specific']} sys / {e['misses_universal']} univ)",
                file=sys.stderr,
            )
