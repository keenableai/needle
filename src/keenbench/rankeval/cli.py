import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from keenbench.rankeval.pipeline import EvalQuery, run_rbp
from keenbench.shared.llm import OpenRouterClient
from keenbench.shared.sampling import sample_stratified, sample_uniform
from keenbench.shared.search import ExaClient, KeenableClient, SearchClient

DEFAULT_JUDGE_MODEL = "google/gemini-3-flash-preview"


def _load_query_rows(path: str) -> list[dict]:
    rows: list[dict] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            rows.append({"query_text": line})
            continue
        if isinstance(obj, dict):
            if obj.get("query_text"):
                rows.append(
                    {
                        "query_text": str(obj["query_text"]),
                        "topical_domain": str(obj.get("topical_domain") or "other"),
                        "hour_ts": obj.get("hour_ts"),
                    }
                )
        elif isinstance(obj, str):
            rows.append({"query_text": obj})
    return rows


def _today_for_row(row: dict, fallback: str) -> str:
    raw = row.get("hour_ts")
    if raw:
        try:
            return datetime.fromisoformat(str(raw)).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return fallback


class Rankeval:
    def run(
        self,
        queries: str,
        out: str = "-",
        engines: str | tuple[str, ...] = "keenable,exa",
        num_results: int = 5,
        judge_model: str | None = None,
        keenable_mode: str = "pro",
        exa_concurrency: int = 4,
        limit: int = 0,
        sample: str = "stratified",
        seed: int = 0,
        judge_concurrency: int = 8,
    ) -> None:
        openrouter_key = os.environ.get("OPENROUTER_API_KEY")
        if not openrouter_key:
            raise SystemExit("error: OPENROUTER_API_KEY is not set (needed for the judge)")

        rows = _load_query_rows(queries)
        if limit > 0 and len(rows) > limit:
            if sample == "head":
                rows = rows[:limit]
            elif sample == "uniform":
                rows = sample_uniform(rows, limit, seed)
            elif sample == "stratified":
                rows = sample_stratified(rows, limit, seed)
            else:
                raise SystemExit(
                    f"error: unknown --sample {sample!r} (known: stratified, uniform, head)"
                )
        if not rows:
            raise SystemExit(f"error: no queries loaded from {queries!r}")

        fallback_today = datetime.now(UTC).strftime("%Y-%m-%d")
        eval_queries = [
            EvalQuery(
                text=r["query_text"],
                today=_today_for_row(r, fallback_today),
                topical_domain=str(r.get("topical_domain") or "other"),
            )
            for r in rows
        ]

        if isinstance(engines, str):
            engine_names = [e.strip() for e in engines.split(",") if e.strip()]
        else:
            engine_names = [str(e).strip() for e in engines]

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
                clients[name] = ExaClient(api_key=exa_key, max_concurrency=exa_concurrency)
            else:
                raise SystemExit(f"error: unknown engine {name!r} (known: keenable, exa)")

        model = judge_model or os.environ.get("KEENBENCH_JUDGE_MODEL") or DEFAULT_JUDGE_MODEL
        judge = OpenRouterClient(api_key=openrouter_key, model=model)

        async def _go() -> dict:
            try:
                return await run_rbp(
                    eval_queries,
                    clients,
                    judge,
                    num_results=num_results,
                    judge_concurrency=judge_concurrency,
                )
            finally:
                await judge.aclose()
                for c in clients.values():
                    await c.aclose()

        report = asyncio.run(_go())
        report["judge_model"] = model

        text = json.dumps(report, ensure_ascii=False, indent=2)
        if out == "-":
            print(text)
        else:
            Path(out).write_text(text + "\n", encoding="utf-8")

        print(
            f"\nrankeval: {report['num_queries']} queries, judge={model}",
            file=sys.stderr,
        )
        for name, e in report["engines"].items():
            print(
                f"  {name:10s} RBP@5 = {e['mean_rbp_at_5']:.4f}  "
                f"({e['num_scored']}/{report['num_queries']} scored; max {e['rbp_max']:.3f}; "
                f"{e['search_errors']} search errs, {e['judge_errors']} judge errs)",
                file=sys.stderr,
            )
