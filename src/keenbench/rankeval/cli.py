import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from keenbench.rankeval.pipeline import run_rbp
from keenbench.shared.llm import OpenRouterClient
from keenbench.shared.search import ExaClient, KeenableClient, SearchClient

DEFAULT_JUDGE_MODEL = "google/gemini-3-flash-preview"


def _load_queries(path: str) -> list[str]:
    queries: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            queries.append(line)
            continue
        if isinstance(obj, dict):
            text = obj.get("query_text")
            if text:
                queries.append(str(text))
        elif isinstance(obj, str):
            queries.append(obj)
    return queries


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
        judge_concurrency: int = 8,
    ) -> None:
        openrouter_key = os.environ.get("OPENROUTER_API_KEY")
        if not openrouter_key:
            raise SystemExit("error: OPENROUTER_API_KEY is not set (needed for the judge)")

        query_texts = _load_queries(queries)
        if limit > 0:
            query_texts = query_texts[:limit]
        if not query_texts:
            raise SystemExit(f"error: no queries loaded from {queries!r}")

        # Fire turns a comma-separated --engines value into a tuple; accept both.
        if isinstance(engines, str):
            engine_names = [e.strip() for e in engines.split(",") if e.strip()]
        else:
            engine_names = [str(e).strip() for e in engines]

        clients: dict[str, SearchClient] = {}
        for name in engine_names:
            if name == "keenable":
                clients[name] = KeenableClient(mode=keenable_mode)
            elif name == "exa":
                exa_key = os.environ.get("EXA_API_KEY")
                if not exa_key:
                    raise SystemExit("error: EXA_API_KEY is not set (needed for the exa engine)")
                clients[name] = ExaClient(api_key=exa_key, max_concurrency=exa_concurrency)
            else:
                raise SystemExit(f"error: unknown engine {name!r} (known: keenable, exa)")

        model = judge_model or os.environ.get("KEENBENCH_JUDGE_MODEL") or DEFAULT_JUDGE_MODEL
        judge = OpenRouterClient(api_key=openrouter_key, model=model)
        today = datetime.now(UTC).strftime("%Y-%m-%d")

        async def _go() -> dict:
            try:
                return await run_rbp(
                    query_texts,
                    clients,
                    judge,
                    num_results=num_results,
                    today=today,
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
                f"(max {e['rbp_max']:.3f}; {e['search_errors']} search errs, "
                f"{e['judge_errors']} judge errs)",
                file=sys.stderr,
            )
