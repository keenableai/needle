import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from keenbench.rankeval.pipeline import EvalQuery, run_rbp
from keenbench.shared.llm import OpenRouterClient, resolve_judge_model
from keenbench.shared.sampling import sample as sample_rows
from keenbench.shared.search import build_search_clients


def _load_query_rows(path: str) -> list[dict]:
    rows: list[dict] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            rows.append({"query_text": line, "topical_domain": "other"})
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
            rows.append({"query_text": obj, "topical_domain": "other"})
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
        exa_highlight_chars: int = 500,
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
            try:
                rows = sample_rows(rows, limit, seed, strategy=sample)
            except ValueError as exc:
                raise SystemExit(f"error: --sample: {exc}") from exc
        if not rows:
            raise SystemExit(f"error: no queries loaded from {queries!r}")

        fallback_today = datetime.now(UTC).strftime("%Y-%m-%d")
        eval_queries = [
            EvalQuery(text=r["query_text"], today=_today_for_row(r, fallback_today)) for r in rows
        ]

        if isinstance(engines, str):
            engine_names = [e.strip() for e in engines.split(",") if e.strip()]
        else:
            engine_names = [str(e).strip() for e in engines]

        try:
            clients = build_search_clients(
                engine_names,
                keenable_mode=keenable_mode,
                exa_concurrency=exa_concurrency,
                exa_highlight_chars=exa_highlight_chars,
            )
        except ValueError as exc:
            raise SystemExit(f"error: {exc}") from exc

        model = resolve_judge_model(judge_model)
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
