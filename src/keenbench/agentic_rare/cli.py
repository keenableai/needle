import json
import sys
from datetime import datetime

from keenbench.agentic_rare.io import iter_rows, resolve_dataset, write_rows
from keenbench.shared.cli import current_hour, run_ndcg_eval, sample_or_exit
from keenbench.shared.hf import DEFAULT_DATASET
from keenbench.shared.identity import query_hash, query_id
from keenbench.shared.rankeval import EvalQuery
from keenbench.shared.search import DEFAULT_SNIPPET_CHARS

DEFAULT_FILTERED_PATH = "agentic/rare_entity.parquet"
STRATIFY_KEY = "length_bucket"
RARE_PRODUCER_ID = "agentic_rare"


def _query_text(row: dict) -> str:
    return str(row.get("query_text") or row.get("query") or "")


def _as_obj(value: object) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def query_row(row: dict, *, hour_ts: datetime) -> dict:
    text = _query_text(row)
    ts = hour_ts.isoformat()
    origin = {
        "bucket": RARE_PRODUCER_ID,
        "subcategory": f"rare_{row.get('length_bucket') or 'unknown'}",
        "provenance": {
            "producer": RARE_PRODUCER_ID,
            "source": row.get("source"),
            "metadata": _as_obj(row.get("metadata")),
            "hard_words": _as_obj(row.get("hard_words")),
        },
    }
    return {
        "query_id": query_id(text, hour_ts=hour_ts),
        "query_hash": query_hash(text),
        "query_text": text,
        "query_source": RARE_PRODUCER_ID,
        "query_origin": json.dumps(origin, sort_keys=True),
        "hour_ts": ts,
        "query_produced_at": ts,
    }


def _load_rows(queries: str | None, dataset: str, filtered_path: str) -> list[dict]:
    return list(iter_rows(resolve_dataset(queries, dataset, filtered_path)))


class AgenticRare:
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
        rows = sample_or_exit(rows, limit, seed, strategy=sample, key=STRATIFY_KEY)
        write_rows(rows, out)
        print(f"agentic_rare: {len(rows)} queries ({sample})", file=sys.stderr)

    def run(
        self,
        queries: str | None = None,
        out: str = "-",
        queries_out: str | None = None,
        dataset: str = DEFAULT_DATASET,
        filtered_path: str = DEFAULT_FILTERED_PATH,
        engines: str | tuple[str, ...] = "keenable,exa",
        num_results: int = 5,
        snippet_chars: int = DEFAULT_SNIPPET_CHARS,
        limit: int = 0,
        sample: str = "stratified",
        seed: int | None = None,
        judge_model: str | None = None,
        judge_concurrency: int = 8,
    ) -> None:
        rows = _load_rows(queries, dataset, filtered_path)
        rows = sample_or_exit(rows, limit, seed, strategy=sample, key=STRATIFY_KEY)
        if not rows:
            raise SystemExit("error: no queries loaded")

        now, hour_ts = current_hour()
        query_rows = [query_row(r, hour_ts=hour_ts) for r in rows]
        if queries_out:
            write_rows(query_rows, queries_out)

        today = now.strftime("%Y-%m-%d")
        eval_queries = [EvalQuery(text=r["query_text"], today=today) for r in query_rows]
        run_ndcg_eval(
            "agentic_rare",
            eval_queries,
            engines,
            out,
            num_results=num_results,
            snippet_chars=snippet_chars,
            judge_model=judge_model,
            judge_concurrency=judge_concurrency,
        )
