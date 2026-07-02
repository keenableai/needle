"""Scaffolding shared by the benchmark CLIs (flag parsing, errors-to-SystemExit)."""

from collections.abc import Callable
from typing import Any

from keenbench.shared.sampling import sample as sample_rows
from keenbench.shared.search import SearchClient, build_search_clients


def parse_csv(value: str | tuple[str, ...]) -> list[str]:
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(v).strip() for v in value]


def sample_or_exit(
    rows: list[dict[str, Any]],
    limit: int,
    seed: int,
    *,
    strategy: str,
    key: str | Callable[[dict[str, Any]], str] = "topical_domain",
) -> list[dict[str, Any]]:
    if limit <= 0 or len(rows) <= limit:
        return rows
    try:
        return sample_rows(rows, limit, seed, strategy=strategy, key=key)
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
