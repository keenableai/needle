import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from keenbench.freshstream.feeds import SEED_SOURCES, load_sources_from_toml
from keenbench.freshstream.pipeline import run_rss, run_trends
from keenbench.freshstream.trends import GoogleTrendsRssProvider, parse_geos
from keenbench.shared.cli import run_rbp_eval, sample_or_exit
from keenbench.shared.io import write_jsonl
from keenbench.shared.llm import OpenRouterClient, resolve_llm_model
from keenbench.shared.rankeval import EvalQuery


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
            # plain-text query that happens to parse as a JSON scalar (e.g. "1984")
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


class Freshstream:
    def generate(
        self,
        source: str = "rss",
        out: str = "-",
        feeds: str | None = None,
        geos: str = "us-all",
        max_trends: int = 0,
        llm_model: str | None = None,
        max_rows_per_source: int = 50,
        fetch_concurrency: int = 15,
        llm_concurrency: int = 8,
    ) -> None:
        if source not in ("rss", "trending"):
            raise SystemExit(f"error: unsupported --source {source!r} (known: rss, trending)")

        if source == "trending":
            misused = [
                name
                for name, used in (
                    ("--feeds", feeds is not None),
                    ("--fetch-concurrency", fetch_concurrency != 15),
                    ("--max-rows-per-source", max_rows_per_source != 50),
                )
                if used
            ]
        else:
            misused = [
                name
                for name, used in (
                    ("--geos", geos != "us-all"),
                    ("--max-trends", max_trends != 0),
                )
                if used
            ]
        if misused:
            raise SystemExit(f"error: {', '.join(misused)} is not used with --source {source}")

        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise SystemExit("error: OPENROUTER_API_KEY is not set")

        model = resolve_llm_model(llm_model)
        llm = OpenRouterClient(api_key=api_key, model=model)
        hour_ts = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
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
                )

        async def _go():
            try:
                return await pipeline()
            finally:
                await llm.aclose()
                if provider is not None:
                    await provider.aclose()

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
            f"freshstream: {stats.projected} queries from {source_summary} "
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
        snippet_chars: int = 500,
        limit: int = 0,
        sample: str = "stratified",
        seed: int = 0,
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
            "freshstream",
            eval_queries,
            engines,
            out,
            num_results=num_results,
            snippet_chars=snippet_chars,
            judge_model=judge_model,
            judge_concurrency=judge_concurrency,
        )
