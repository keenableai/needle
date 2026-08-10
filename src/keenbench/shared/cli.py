import asyncio
import json
import os
import sys
from collections.abc import Callable, Collection
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


def parse_known_csv(
    value: str | tuple[str, ...], known: Collection[str], *, flag: str
) -> tuple[str, ...]:
    names = tuple(parse_csv(value))
    bad = [v for v in names if v not in known]
    if bad or not names:
        raise SystemExit(
            f"error: unknown {flag} {','.join(bad) or value!r} (known: {', '.join(known)})"
        )
    return names


def as_obj(value: object) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def has_gold_ids(gold: dict) -> bool:
    ids = gold.get("ids")
    return isinstance(ids, dict) and bool(ids)


def current_hour() -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    return now, now.replace(minute=0, second=0, microsecond=0)


async def aclose_all(*clients: Any) -> None:
    for client in clients:
        if client is not None:
            await client.aclose()


def require_openrouter_client(
    model: str, *, purpose: str | None = None, timeout_s: float = 60.0
) -> OpenRouterClient:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        suffix = f" (needed for {purpose})" if purpose else ""
        raise SystemExit(f"error: OPENROUTER_API_KEY is not set{suffix}")
    return OpenRouterClient(api_key=key, model=model, timeout_s=timeout_s)


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
    if not rows:
        raise SystemExit(f"error: no gold rows loaded from {path!r}")
    return rows


def resolve_seed(seed: int | None, hour_ts: datetime | None = None) -> int:
    if seed is not None:
        return seed
    return seed_from_hour_ts(hour_ts or current_hour()[1])


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
    snippet_chars: int = 2000,
    judge_model: str | None = None,
    judge_concurrency: int = 8,
) -> None:
    clients = build_clients_or_exit(engines, snippet_chars=snippet_chars)
    model = resolve_judge_model(judge_model)
    judge = require_openrouter_client(model, purpose="the judge")

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
            await aclose_all(judge, *clients.values())

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
