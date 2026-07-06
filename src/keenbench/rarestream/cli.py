import sys
from datetime import UTC, datetime

from keenbench.rarestream.io import iter_rows, resolve_dataset, write_rows
from keenbench.shared.cli import run_rbp_eval, sample_or_exit
from keenbench.shared.rankeval import EvalQuery
from keenbench.shared.sampling import resolve_seed

DEFAULT_DATASET = "keenable-ai/keenbench-results"
DEFAULT_FILTERED_PATH = "agentic/rare_entity.parquet"
STRATIFY_KEY = "length_bucket"


def _query_text(row: dict) -> str:
    return str(row.get("query_text") or row.get("query") or "")


def _load_rows(queries: str | None, dataset: str, filtered_path: str) -> list[dict]:
    return list(iter_rows(resolve_dataset(queries, dataset, filtered_path)))


class Rarestream:
    def generate(
        self,
        out: str = "-",
        queries: str | None = None,
        dataset: str = DEFAULT_DATASET,
        filtered_path: str = DEFAULT_FILTERED_PATH,
        limit: int = 0,
        sample: str = "stratified",
        seed: int | None = None,
    ) -> None:
        rows = _load_rows(queries, dataset, filtered_path)
        rows = sample_or_exit(rows, limit, resolve_seed(seed), strategy=sample, key=STRATIFY_KEY)
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
        seed: int | None = None,
        judge_model: str | None = None,
        judge_concurrency: int = 8,
    ) -> None:
        rows = _load_rows(queries, dataset, filtered_path)
        rows = sample_or_exit(rows, limit, resolve_seed(seed), strategy=sample, key=STRATIFY_KEY)
        if not rows:
            raise SystemExit("error: no queries loaded")

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        eval_queries = [EvalQuery(text=_query_text(r), today=today) for r in rows]
        run_rbp_eval(
            "rarestream",
            eval_queries,
            engines,
            out,
            num_results=num_results,
            snippet_chars=snippet_chars,
            judge_model=judge_model,
            judge_concurrency=judge_concurrency,
        )
