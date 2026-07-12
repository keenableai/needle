import asyncio
import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from keenbench.shared.io import write_json
from keenbench.shared.judge import DEFAULT_MAX_CONTENT_CHARS
from keenbench.shared.llm import OpenRouterClient, resolve_judge_model
from keenbench.shared.rankeval import EvalQuery, run_rbp
from keenbench.shared.sampling import sample as sample_rows
from keenbench.shared.sampling import seed_from_hour_ts
from keenbench.shared.search import SearchClient, build_search_clients


def parse_csv(value: str | tuple[str, ...]) -> list[str]:
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(v).strip() for v in value]


def as_obj(value: object) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def load_gold_rows(path: str, *, bench: str, gold_ok: Callable[[dict], bool]) -> list[dict]:
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
        obj = as_obj(line)
        if not isinstance(obj, dict) or not obj.get("query_text"):
            continue
        gold = as_obj(obj.get("gold"))
        if not isinstance(gold, dict) or not gold_ok(gold):
            malformed += 1
            continue
        obj["gold"] = gold
        origin = as_obj(obj.get("query_origin"))
        obj["query_origin"] = origin if isinstance(origin, dict) else {}
        rows.append(obj)
    if malformed:
        print(f"{bench}: skipped {malformed} malformed gold rows", file=sys.stderr)
    return rows


def resolve_seed(seed: int | None, hour_ts: datetime | None = None) -> int:
    if seed is not None:
        return seed
    ts = hour_ts or datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    return seed_from_hour_ts(ts)


def sample_or_exit(
    rows: list[dict[str, Any]],
    limit: int,
    seed: int | None,
    *,
    strategy: str,
    key: str | Callable[[dict[str, Any]], str] = "topical_domain",
) -> list[dict[str, Any]]:
    if limit <= 0 or len(rows) <= limit:
        return rows
    try:
        return sample_rows(rows, limit, resolve_seed(seed), strategy=strategy, key=key)
    except ValueError as exc:
        raise SystemExit(f"error: --sample: {exc}") from exc


def build_clients_or_exit(
    engines: str | tuple[str, ...],
    *,
    snippet_chars: int,
) -> dict[str, SearchClient]:
    try:
        return build_search_clients(parse_csv(engines), snippet_chars=snippet_chars)
    except ValueError as exc:
        raise SystemExit(f"error: {exc}") from exc


def run_rbp_eval(
    bench: str,
    eval_queries: list[EvalQuery],
    engines: str | tuple[str, ...],
    out: str,
    *,
    num_results: int = 5,
    snippet_chars: int = 500,
    judge_model: str | None = None,
    judge_concurrency: int = 8,
) -> None:
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if not openrouter_key:
        raise SystemExit("error: OPENROUTER_API_KEY is not set (needed for the judge)")

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

    print(f"\n{bench}: {report['num_queries']} queries, judge={model}", file=sys.stderr)
    for name, e in report["engines"].items():
        print(
            f"  {name:10s} RBP@{num_results} = {e['mean_rbp']:.4f}  "
            f"({e['num_scored']}/{report['num_queries']} scored; max {e['rbp_max']:.3f}; "
            f"{e['search_errors']} search errs, {e['judge_errors']} judge errs)",
            file=sys.stderr,
        )
