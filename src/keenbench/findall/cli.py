import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from keenbench.findall.harness import AgentLLM, resolve_backend
from keenbench.findall.models import (
    AGENT_MODEL_ENV,
    DEFAULT_AGENT_MODEL,
    SUITES,
    build_task_row,
    serialize_row,
)
from keenbench.findall.score import GoldTask, run_findall
from keenbench.findall.sources import EdgarFtsClient, HnClient, edgar_tasks, hn_tasks
from keenbench.shared.cli import parse_csv, sample_or_exit
from keenbench.shared.io import write_json, write_jsonl


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
        if not isinstance(gold, dict) or gold.get("kind") not in ("set", "stat"):
            malformed += 1
            continue
        obj["gold"] = gold
        origin = _as_obj(obj.get("query_origin"))
        obj["query_origin"] = origin if isinstance(origin, dict) else {}
        rows.append(obj)
    if malformed:
        print(f"findall: skipped {malformed} malformed gold rows", file=sys.stderr)
    return rows


def _gold_task(row: dict) -> GoldTask:
    gold = row["gold"]
    origin = row.get("query_origin") or {}
    return GoldTask(
        text=str(row["query_text"]),
        kind=str(gold["kind"]),
        suite=str(origin.get("suite") or "unknown"),
        bucket=str(origin.get("bucket") or "unknown"),
        entities=tuple(gold.get("entities") or []),
        stat_value=float(gold.get("value") or 0.0),
        stat_rel_tol=float(gold.get("rel_tol") or 0.25),
    )


class Findall:
    def generate(
        self,
        out: str = "-",
        suites: str | tuple[str, ...] = "hn,edgar",
    ) -> None:
        suite_names = tuple(parse_csv(suites))
        unknown = [s for s in suite_names if s not in SUITES]
        if unknown or not suite_names:
            raise SystemExit(
                f"error: unknown --suites {','.join(unknown) or suites!r} "
                f"(known: {', '.join(SUITES)})"
            )
        now = datetime.now(UTC)
        hour_ts = now.replace(minute=0, second=0, microsecond=0)

        hn = HnClient() if "hn" in suite_names else None
        edgar = EdgarFtsClient(max_concurrency=2) if "edgar" in suite_names else None

        async def _go() -> list:
            tasks = []
            try:
                if hn is not None:
                    tasks.extend(await hn_tasks(hn, now=now))
                if edgar is not None:
                    tasks.extend(await edgar_tasks(edgar, now=now))
            finally:
                for client in (hn, edgar):
                    if client is not None:
                        await client.aclose()
            return tasks

        tasks = asyncio.run(_go())
        rows = [build_task_row(t, hour_ts=hour_ts) for t in tasks]
        write_jsonl([serialize_row(r) for r in rows], out)
        sets = sum(1 for t in tasks if t.stat_value is None)
        print(
            f"findall: {len(rows)} tasks (enumerate={sets}, stat={len(rows) - sets})",
            file=sys.stderr,
        )

    def run(
        self,
        queries: str,
        out: str = "-",
        backends: str | tuple[str, ...] = "keenable,webql",
        budget_usd: float = 0.25,
        agent_model: str | None = None,
        max_turns: int = 20,
        concurrency: int = 2,
        limit: int = 0,
        sample: str = "stratified",
        seed: int = 0,
    ) -> None:
        rows = _load_gold_rows(queries)
        if not rows:
            raise SystemExit(f"error: no gold task rows loaded from {queries!r}")
        rows = sample_or_exit(
            rows,
            limit,
            seed,
            strategy=sample,
            key=lambda r: (
                f"{r['query_origin'].get('suite', '?')}:{r['query_origin'].get('bucket', '?')}"
            ),
        )
        tasks = [_gold_task(r) for r in rows]

        try:
            specs = [resolve_backend(n) for n in parse_csv(backends)]
        except ValueError as exc:
            raise SystemExit(f"error: {exc}") from exc

        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise SystemExit("error: OPENROUTER_API_KEY is not set (needed for the agent)")
        model = agent_model or os.environ.get(AGENT_MODEL_ENV) or DEFAULT_AGENT_MODEL
        llm = AgentLLM(api_key=key, model=model)

        async def _go() -> dict:
            try:
                return await run_findall(
                    tasks,
                    specs,
                    llm,
                    budget_usd=budget_usd,
                    max_turns=max_turns,
                    concurrency=concurrency,
                )
            finally:
                await llm.aclose()

        report = asyncio.run(_go())
        write_json(report, out)

        print(
            f"\nfindall: {report['num_queries']} tasks, budget ${budget_usd:.2f}, agent {model}",
            file=sys.stderr,
        )
        for name, b in report["backends"].items():
            print(
                f"  {name:10s} score = {b['mean_score']:.4f}  "
                f"(set recall = {b['set_recall']:.3f}, precision = {b['set_precision']:.3f}; "
                f"stat within-tol = {b['stat_within_tol']:.3f}; "
                f"${b['mean_spent_usd']:.3f}/task, {b['mean_tool_calls']:.1f} tool calls; "
                f"{b['num_scored']} scored, {b['errors']} errors)",
                file=sys.stderr,
            )
