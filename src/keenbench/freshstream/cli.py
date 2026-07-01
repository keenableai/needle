import asyncio
import os
import sys
from datetime import UTC, datetime

from keenbench.freshstream.feeds import SEED_SOURCES, load_sources_from_toml
from keenbench.freshstream.pipeline import run_rss
from keenbench.shared.io import write_jsonl, write_stdout
from keenbench.shared.llm import OpenRouterClient

DEFAULT_MODEL = "google/gemini-2.5-flash-lite"


class Freshstream:
    def run(
        self,
        source: str = "rss",
        out: str = "-",
        feeds: str | None = None,
        llm_model: str | None = None,
        max_rows_per_source: int = 50,
        fetch_concurrency: int = 15,
        llm_concurrency: int = 8,
    ) -> None:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise SystemExit("error: OPENROUTER_API_KEY is not set")

        model = llm_model or os.environ.get("KEENBENCH_LLM_MODEL", DEFAULT_MODEL)
        sources = load_sources_from_toml(feeds) if feeds else SEED_SOURCES
        llm = OpenRouterClient(api_key=api_key, model=model)
        hour_ts = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)

        rows, stats = asyncio.run(
            run_rss(
                sources,
                llm,
                hour_ts=hour_ts,
                fetch_concurrency=fetch_concurrency,
                llm_concurrency=llm_concurrency,
                max_rows_per_source=max_rows_per_source,
            )
        )

        records = [r.to_dict() for r in rows]
        if out == "-":
            write_stdout(records)
        else:
            write_jsonl(records, out)

        print(
            f"freshstream: {stats.projected} queries from {stats.candidates}/{stats.feeds} feeds "
            f"({stats.no_news_event} evergreen, {stats.llm_errors} llm errors, "
            f"{stats.duplicates} dupes)",
            file=sys.stderr,
        )
