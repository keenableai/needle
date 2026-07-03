import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from keenbench.scholar.generate import GenStats, run_generate
from keenbench.scholar.idconv import IdConverter
from keenbench.scholar.models import AGE_BUCKETS, serialize_row
from keenbench.scholar.score import GoldPaper, run_papers
from keenbench.scholar.sources import ArxivClient, EuropePmcClient
from keenbench.shared.cli import build_clients_or_exit, parse_csv, sample_or_exit
from keenbench.shared.io import write_json, write_jsonl
from keenbench.shared.llm import OpenRouterClient, resolve_llm_model

KNOWN_SUITES = ("arxiv", "europepmc")


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
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(obj, dict) or not obj.get("query_text"):
            continue
        gold = obj.get("gold")
        if isinstance(gold, str):
            try:
                gold = json.loads(gold)
            except json.JSONDecodeError:
                malformed += 1
                continue
        ids = gold.get("ids") if isinstance(gold, dict) else None
        if not isinstance(ids, dict) or not ids:
            malformed += 1
            continue
        obj["gold"] = gold
        origin = obj.get("query_origin")
        if isinstance(origin, str):
            try:
                origin = json.loads(origin)
            except json.JSONDecodeError:
                origin = {}
        obj["query_origin"] = origin if isinstance(origin, dict) else {}
        rows.append(obj)
    if malformed:
        print(f"scholar: skipped {malformed} malformed gold rows", file=sys.stderr)
    return rows


def _gold_paper(row: dict) -> GoldPaper:
    gold = row["gold"]
    origin = row.get("query_origin") or {}
    return GoldPaper(
        text=str(row["query_text"]),
        paper_key=str(gold.get("paper_key") or ""),
        ids={k: str(v) for k, v in (gold.get("ids") or {}).items()},
        bucket=str(origin.get("bucket") or "unknown"),
        suite=str(origin.get("suite") or gold.get("suite") or "unknown"),
        age_bucket=str(gold.get("age_bucket") or "unknown"),
        domain=str(gold.get("domain") or "unknown"),
    )


class Scholar:
    def generate(
        self,
        out: str = "-",
        suites: str | tuple[str, ...] = "arxiv,europepmc",
        age_buckets: str | tuple[str, ...] = "7d,30d,1y",
        per_cell: int = 10,
        seed: int = 0,
        llm_model: str | None = None,
        body_concurrency: int = 8,
    ) -> None:
        suite_names = tuple(parse_csv(suites))
        unknown = [s for s in suite_names if s not in KNOWN_SUITES]
        if unknown or not suite_names:
            raise SystemExit(
                f"error: unknown --suites {','.join(unknown) or suites!r} "
                f"(known: {', '.join(KNOWN_SUITES)})"
            )
        age_names = tuple(parse_csv(age_buckets))
        bad_ages = [a for a in age_names if a not in AGE_BUCKETS]
        if bad_ages or not age_names:
            raise SystemExit(
                f"error: unknown --age-buckets {','.join(bad_ages) or age_buckets!r} "
                f"(known: {', '.join(AGE_BUCKETS)})"
            )

        now = datetime.now(UTC)
        hour_ts = now.replace(minute=0, second=0, microsecond=0)

        arxiv = ArxivClient() if "arxiv" in suite_names else None
        europepmc = EuropePmcClient() if "europepmc" in suite_names else None

        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise SystemExit("error: OPENROUTER_API_KEY is not set (needed for body queries)")
        model = resolve_llm_model(llm_model)
        llm = OpenRouterClient(api_key=key, model=model)

        async def _go() -> tuple[list[dict], GenStats]:
            try:
                return await run_generate(
                    arxiv=arxiv,
                    europepmc=europepmc,
                    llm=llm,
                    hour_ts=hour_ts,
                    now=now,
                    age_buckets=age_names,
                    per_cell=per_cell,
                    seed=seed,
                    body_concurrency=body_concurrency,
                )
            finally:
                for client in (arxiv, europepmc):
                    if client is not None:
                        await client.aclose()
                await llm.aclose()

        rows, stats = asyncio.run(_go())
        write_jsonl([serialize_row(r) for r in rows], out)
        print(
            f"scholar: {stats.title_rows + stats.body_rows} queries from {stats.papers} paired "
            f"papers (title={stats.title_rows}, body={stats.body_rows}; "
            f"{stats.candidates} candidates; body drops: fetch={stats.body_fetch_fail}, "
            f"no_query={stats.body_no_query}, leak={stats.body_leak_rejected}, "
            f"llm_err={stats.llm_errors}; short_cells={stats.short_cells})",
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
        resolve_pmcids: bool = True,
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
                f"{r['query_origin'].get('bucket', '?')}:{r['gold'].get('age_bucket', '?')}"
            ),
        )
        gold_papers = [_gold_paper(r) for r in rows]

        clients = build_clients_or_exit(engines, snippet_chars=snippet_chars)
        need_idconv = resolve_pmcids and any("pmid" in g.ids for g in gold_papers)
        idconv = IdConverter() if need_idconv else None

        async def _go() -> dict:
            try:
                return await run_papers(
                    gold_papers,
                    clients,
                    num_results=num_results,
                    snippet_chars=snippet_chars,
                    idconv=idconv,
                )
            finally:
                for c in clients.values():
                    await c.aclose()
                if idconv is not None:
                    await idconv.aclose()

        report = asyncio.run(_go())
        write_json(report, out)

        print(
            f"\nscholar: {report['num_queries']} queries, top-{num_results}",
            file=sys.stderr,
        )
        for name, e in report["engines"].items():
            si = e["shallow_index"]
            si_rate = si["shallow_index_rate"]
            si_str = f"{si_rate:.3f}" if si_rate is not None else "n/a"
            print(
                f"  {name:10s} recall@{num_results} = {e['recall_at_k']:.4f}  "
                f"MRR = {e['mrr_at_k']:.4f}  "
                f"({e['num_scored']}/{report['num_queries']} scored; "
                f"{e['search_errors']} search errs; "
                f"shallow-index-rate = {si_str}; "
                f"misses: {e['misses_system_specific']} sys / {e['misses_universal']} univ)",
                file=sys.stderr,
            )
