import asyncio
import os
import sys
from datetime import UTC, datetime

from huggingface_hub import hf_hub_download

from keenbench.rarestream.io import iter_rows, write_rows
from keenbench.shared.cli import build_clients_or_exit, sample_or_exit
from keenbench.shared.io import write_json
from keenbench.shared.judge import DEFAULT_MAX_CONTENT_CHARS
from keenbench.shared.llm import OpenRouterClient, resolve_judge_model
from keenbench.shared.rankeval import EvalQuery, run_rbp

DEFAULT_DATASET = "keenable-ai/keenbench-results"
DEFAULT_FILTERED_PATH = "agentic/rare_entity.parquet"


def _query_text(row: dict) -> str:
    return str(row.get("query_text") or row.get("query") or "")


def _load_rows(queries: str | None, dataset: str, filtered_path: str) -> list[dict]:
    if queries is None:
        queries = hf_hub_download(dataset, filtered_path, repo_type="dataset")
    return list(iter_rows(queries))


class Rarestream:
    def generate(
        self,
        out: str = "-",
        queries: str | None = None,
        dataset: str = DEFAULT_DATASET,
        filtered_path: str = DEFAULT_FILTERED_PATH,
        limit: int = 0,
        sample: str = "stratified",
        seed: int = 0,
        by: str = "length_bucket",
    ) -> None:
        rows = _load_rows(queries, dataset, filtered_path)
        rows = sample_or_exit(rows, limit, seed, strategy=sample, key=by)
        write_rows(rows, out)
        print(f"rarestream: {len(rows)} queries ({sample})", file=sys.stderr)

    def run(
        self,
        queries: str | None = None,
        out: str = "-",
        dataset: str = DEFAULT_DATASET,
        filtered_path: str = DEFAULT_FILTERED_PATH,
        engines: str | tuple[str, ...] = "keenable,exa",
        num_results: int = 5,
        snippet_chars: int = 500,
        limit: int = 0,
        sample: str = "stratified",
        seed: int = 0,
        by: str = "length_bucket",
        judge_model: str | None = None,
        judge_concurrency: int = 8,
    ) -> None:
        openrouter_key = os.environ.get("OPENROUTER_API_KEY")
        if not openrouter_key:
            raise SystemExit("error: OPENROUTER_API_KEY is not set (needed for the judge)")

        rows = _load_rows(queries, dataset, filtered_path)
        rows = sample_or_exit(rows, limit, seed, strategy=sample, key=by)
        if not rows:
            raise SystemExit("error: no queries loaded")

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        eval_queries = [EvalQuery(text=_query_text(r), today=today) for r in rows]

        clients = build_clients_or_exit(engines, snippet_chars=snippet_chars)
        model = resolve_judge_model(judge_model)
        judge = OpenRouterClient(api_key=openrouter_key, model=model)

        async def _go() -> dict:
            try:
                return await run_rbp(
                    eval_queries,
                    clients,
                    judge,
                    num_results=num_results,
                    k=num_results,
                    judge_concurrency=judge_concurrency,
                    max_content_chars=snippet_chars or DEFAULT_MAX_CONTENT_CHARS,
                )
            finally:
                await judge.aclose()
                for c in clients.values():
                    await c.aclose()

        report = asyncio.run(_go())
        report["judge_model"] = model
        write_json(report, out)

        print(f"\nrarestream: {report['num_queries']} queries, judge={model}", file=sys.stderr)
        for name, e in report["engines"].items():
            print(
                f"  {name:10s} RBP@{num_results} = {e['mean_rbp']:.4f}  "
                f"({e['num_scored']}/{report['num_queries']} scored; max {e['rbp_max']:.3f}; "
                f"{e['search_errors']} search errs, {e['judge_errors']} judge errs)",
                file=sys.stderr,
            )
