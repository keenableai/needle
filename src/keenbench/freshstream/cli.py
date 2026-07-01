import asyncio
import os
import sys
from datetime import UTC, datetime

from keenbench.freshstream.feeds import SEED_SOURCES, load_sources_from_toml
from keenbench.freshstream.pipeline import run_rss, run_trends
from keenbench.freshstream.trends import GoogleTrendsRssProvider
from keenbench.shared.io import write_jsonl, write_stdout
from keenbench.shared.llm import OpenRouterClient

DEFAULT_MODEL = "google/gemini-2.5-flash-lite"


class Freshstream:
    def run(
        self,
        source: str = "rss",
        out: str = "-",
        feeds: str | None = None,
        geo: str = "US",
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
                for name, used in (("--geo", geo != "US"), ("--max-trends", max_trends != 0))
                if used
            ]
        if misused:
            raise SystemExit(f"error: {', '.join(misused)} is not used with --source {source}")

        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise SystemExit("error: OPENROUTER_API_KEY is not set")

        model = llm_model or os.environ.get("KEENBENCH_LLM_MODEL") or DEFAULT_MODEL
        llm = OpenRouterClient(api_key=api_key, model=model)
        hour_ts = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        llm_concurrency = max(1, llm_concurrency)

        if source == "trending":

            def pipeline():
                return run_trends(
                    GoogleTrendsRssProvider(geo=geo),
                    llm,
                    hour_ts=hour_ts,
                    max_trends=max_trends,
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

        try:
            rows, stats = asyncio.run(_go())
        except ValueError as exc:
            raise SystemExit(f"error: {exc}") from exc

        records = [r.to_dict() for r in rows]
        if out == "-":
            write_stdout(records)
        else:
            write_jsonl(records, out)

        if source == "trending":
            source_summary = f"{stats.candidates} {geo} trends"
        else:
            source_summary = f"{stats.candidates} candidates across {stats.feeds} feeds"
        print(
            f"freshstream: {stats.projected} queries from {source_summary} "
            f"({stats.no_news_event} evergreen, {stats.llm_errors} llm errors, "
            f"{stats.duplicates} dupes)",
            file=sys.stderr,
        )
