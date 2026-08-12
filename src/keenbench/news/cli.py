import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from keenbench.news.feeds import SEED_SOURCES, load_sources_from_toml
from keenbench.news.pipeline import run_rss, run_trends
from keenbench.news.trends import GoogleTrendsRssProvider, parse_geos
from keenbench.shared.cli import (
    aclose_all,
    current_hour,
    require_openrouter_client,
    run_rbp_eval,
    sample_or_exit,
)
from keenbench.shared.io import write_jsonl
from keenbench.shared.llm import resolve_llm_model
from keenbench.shared.rankeval import EvalQuery
from keenbench.shared.search import DEFAULT_SNIPPET_CHARS


def _read_queries_file(path: str) -> list[str]:
    try:
        return Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SystemExit(f"error: could not read --queries {path!r}: {exc}") from exc


def _load_query_rows(path: str) -> list[dict]:
    rows: list[dict] = []
    for line in _read_queries_file(path):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            obj = line
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
        else:
            rows.append({"query_text": line, "topical_domain": "other"})
    return rows


def _today_for_row(row: dict, fallback: str) -> str:
    raw = row.get("hour_ts")
    if raw:
        try:
            return datetime.fromisoformat(str(raw)).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return fallback


class News:
    def generate(
        self,
        source: str = "rss",
        out: str = "-",
        feeds: str | None = None,
        geos: str | None = None,
        max_trends: int | None = None,
        llm_model: str | None = None,
        max_rows_per_source: int | None = None,
        fetch_concurrency: int | None = None,
        llm_concurrency: int = 8,
        min_candidates: int | None = None,
    ) -> None:
        if source not in ("rss", "trending"):
            raise SystemExit(f"error: unsupported --source {source!r} (known: rss, trending)")

        if source == "trending":
            misused = [
                name
                for name, used in (
                    ("--feeds", feeds is not None),
                    ("--fetch-concurrency", fetch_concurrency is not None),
                    ("--max-rows-per-source", max_rows_per_source is not None),
                    ("--min-candidates", min_candidates is not None),
                )
                if used
            ]
        else:
            misused = [
                name
                for name, used in (
                    ("--geos", geos is not None),
                    ("--max-trends", max_trends is not None),
                )
                if used
            ]
        if misused:
            raise SystemExit(f"error: {', '.join(misused)} is not used with --source {source}")

        geos = "us-all" if geos is None else geos
        max_trends = 0 if max_trends is None else max_trends
        max_rows_per_source = 50 if max_rows_per_source is None else max_rows_per_source
        fetch_concurrency = 15 if fetch_concurrency is None else fetch_concurrency
        min_candidates = 30 if min_candidates is None else min_candidates

        llm = require_openrouter_client(resolve_llm_model(llm_model))
        _, hour_ts = current_hour()
        llm_concurrency = max(1, llm_concurrency)

        provider = None
        if source == "trending":
            try:
                geo_list = parse_geos(geos)
            except ValueError as exc:
                raise SystemExit(f"error: --geos: {exc}") from exc
            provider = GoogleTrendsRssProvider()

            def pipeline():
                return run_trends(
                    provider,
                    llm,
                    hour_ts=hour_ts,
                    max_trends=max_trends,
                    geos=geo_list,
                    llm_concurrency=llm_concurrency,
                )
        else:
            if feeds:
                try:
                    sources = load_sources_from_toml(feeds)
                except (OSError, ValueError, KeyError) as exc:
                    raise SystemExit(f"error: could not load --feeds {feeds!r}: {exc}") from exc
            else:
                sources = SEED_SOURCES

            def pipeline():
                return run_rss(
                    sources,
                    llm,
                    hour_ts=hour_ts,
                    fetch_concurrency=max(1, fetch_concurrency),
                    llm_concurrency=llm_concurrency,
                    max_rows_per_source=max_rows_per_source,
                    min_candidates=min_candidates,
                )

        async def _go():
            try:
                return await pipeline()
            finally:
                await aclose_all(llm, provider)

        try:
            rows, stats = asyncio.run(_go())
        except ValueError as exc:
            raise SystemExit(f"error: {exc}") from exc

        records = [r.to_dict() for r in rows]
        write_jsonl(records, out)

        if source == "trending":
            source_summary = (
                f"{stats.candidates} trends across {len(geo_list)} geos "
                f"({stats.fetch_errors} geo fetch errors)"
            )
        else:
            source_summary = f"{stats.candidates} candidates across {stats.feeds} feeds"
        print(
            f"news: {stats.projected} queries from {source_summary} "
            f"({stats.no_news_event} evergreen, {stats.llm_errors} llm errors, "
            f"{stats.duplicates} dupes)",
            file=sys.stderr,
        )

    def run(
        self,
        queries: str,
        out: str = "-",
        engines: str | tuple[str, ...] = "keenable,exa",
        num_results: int = 5,
        snippet_chars: int = DEFAULT_SNIPPET_CHARS,
        limit: int = 0,
        sample: str = "stratified",
        seed: int | None = None,
        judge_model: str | None = None,
        judge_concurrency: int = 8,
    ) -> None:
        rows = _load_query_rows(queries)
        rows = sample_or_exit(rows, limit, seed, strategy=sample)
        if not rows:
            raise SystemExit(f"error: no queries loaded from {queries!r}")

        fallback_today = datetime.now(UTC).strftime("%Y-%m-%d")
        eval_queries = [
            EvalQuery(text=r["query_text"], today=_today_for_row(r, fallback_today)) for r in rows
        ]
        run_rbp_eval(
            "news",
            eval_queries,
            engines,
            out,
            num_results=num_results,
            snippet_chars=snippet_chars,
            judge_model=judge_model,
            judge_concurrency=judge_concurrency,
        )
