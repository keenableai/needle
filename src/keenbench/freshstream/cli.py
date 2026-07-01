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
        llm_model: str | None = None,
        max_rows_per_source: int = 50,
        fetch_concurrency: int = 15,
        llm_concurrency: int = 8,
    ) -> None:
        if source not in ("rss", "trending"):
            raise SystemExit(f"error: unsupported --source {source!r} (known: rss, trending)")

        fetch_concurrency = max(1, fetch_concurrency)
        llm_concurrency = max(1, llm_concurrency)

        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise SystemExit("error: OPENROUTER_API_KEY is not set")

        model = llm_model or os.environ.get("KEENBENCH_LLM_MODEL") or DEFAULT_MODEL
        llm = OpenRouterClient(api_key=api_key, model=model)
        hour_ts = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)

        if source == "trending":

            async def _go():
                try:
                    return await run_trends(
                        GoogleTrendsRssProvider(geo=geo),
                        llm,
                        hour_ts=hour_ts,
                        llm_concurrency=llm_concurrency,
                    )
                finally:
                    await llm.aclose()

            unit = f"{geo} trends"
        else:
            if feeds:
                try:
                    sources = load_sources_from_toml(feeds)
                except (OSError, ValueError, KeyError) as exc:
                    raise SystemExit(f"error: could not load --feeds {feeds!r}: {exc}") from exc
            else:
                sources = SEED_SOURCES

            async def _go():
                try:
                    return await run_rss(
                        sources,
                        llm,
                        hour_ts=hour_ts,
                        fetch_concurrency=fetch_concurrency,
                        llm_concurrency=llm_concurrency,
                        max_rows_per_source=max_rows_per_source,
                    )
                finally:
                    await llm.aclose()

            unit = "feeds"

        rows, stats = asyncio.run(_go())

        records = [r.to_dict() for r in rows]
        if out == "-":
            write_stdout(records)
        else:
            write_jsonl(records, out)

        print(
            f"freshstream: {stats.projected} queries from {stats.candidates} {unit} "
            f"({stats.no_news_event} evergreen, {stats.llm_errors} llm errors, "
            f"{stats.duplicates} dupes)",
            file=sys.stderr,
        )
