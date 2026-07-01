# keenbench

[![CI](https://github.com/keenableai/keenbench/actions/workflows/ci.yaml/badge.svg)](https://github.com/keenableai/keenbench/actions/workflows/ci.yaml)

A collection of search/retrieval benchmarks and query-stream generators from
[Keenable.ai](https://keenable.ai). Each benchmark is a self-contained module
under the `keenbench` package, exposed as a `keenbench <benchmark>` subcommand.

| Module | What it does | Status |
| --- | --- | --- |
| [`freshstream`](#freshstream) | Mine live RSS (and, soon, Google Trends) and project each item into a fresh, terse search query | RSS path shipped |

## Install

Uses [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## freshstream

Mines what's trending *right now* and turns it into keyword-style search
queries — the kind of fast-decaying, time-sensitive queries a search engine has
to keep fresh. Two independent real-time streams feed one cohort, both tagged
`query_source = "fresh-queries"`:

1. **RSS firehose** (`query_origin.bucket = "rss"`) — fetch ~124 curated public
   feeds, keep the newest item per feed inside a freshness window (1h for most
   feeds, 168h for academic papers), and project each survivor into a query via
   an LLM. Evergreen content (explainers, how-tos, reviews, opinion) is refused
   with a `NO_NEWS_EVENT` sentinel and dropped.
2. **Google Trends** (`query_origin.bucket = "trending"`) — *not yet shipped*;
   the provider protocol and pipeline hooks are in place.

### Run

Projection goes through [OpenRouter](https://openrouter.ai) (OpenAI-compatible),
so a single key reaches Claude, GPT, Gemini and others. The CLI auto-loads a
`.env` from the working directory (copy [`.env.example`](.env.example)); a real
exported variable takes precedence.

```bash
cp .env.example .env    # then set OPENROUTER_API_KEY
# default model is google/gemini-2.5-flash-lite; override with --llm-model or $KEENBENCH_LLM_MODEL
keenbench freshstream run --out queries.jsonl
```

Each output line is one canonical query row:

```json
{
  "query_id": "a3f2b9c1e8d04f7a_2026-07-01T14",
  "query_hash": "a3f2b9c1e8d04f7a",
  "query_text": "acme thing launch",
  "query_source": "fresh-queries",
  "query_origin": {
    "bucket": "rss",
    "topical_domain": "tech",
    "subcategory": "rss_tech",
    "provenance": {"producer": "rss_queries", "source_kind": "rss_news", "url": "...", "title": "..."}
  },
  "hour_ts": "2026-07-01T14:00:00+00:00",
  "query_produced_at": "2026-07-01T14:00:00+00:00"
}
```

`query_id` is deterministic from `(query_text, hour_ts)`, so re-running the same
hour produces byte-identical rows.

### Custom feed list

The built-in seed list is a curated set of ~124 US feeds, defined in
[`src/keenbench/freshstream/configs/feeds.default.toml`](src/keenbench/freshstream/configs/feeds.default.toml)
(the single source of truth — `SEED_SOURCES` loads it at import). Copy it, edit,
and pass your version with `--feeds`:

```bash
keenbench freshstream run --feeds my-feeds.toml --out queries.jsonl
```

### As a library

The pipeline is pure — feeds + an LLM client in, query rows out — so it drives
from a notebook or scheduler too:

```python
import asyncio
from datetime import UTC, datetime
from keenbench.freshstream import run_rss
from keenbench.freshstream.feeds import SEED_SOURCES
from keenbench.shared.llm import OpenRouterClient

llm = OpenRouterClient(api_key="sk-or-...", model="google/gemini-2.5-flash-lite")
hour_ts = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
rows, stats = asyncio.run(run_rss(SEED_SOURCES, llm, hour_ts=hour_ts))
```

Any object with an errors-as-data
`async complete(prompt, *, max_tokens, reasoning_effort) -> (text, error)`
method satisfies the `LLMClient` protocol.

## Search clients

`keenbench.shared.search` provides a common client interface across search
engines — a `SearchResult` (`url`, `title`, `snippet`, `published_date`,
`score`, `raw`) and a `SearchClient` protocol
(`async search(query, *, num_results) -> (results, error)`, errors-as-data,
never raises). Shipped engines:

| Client | Endpoint | Key |
| --- | --- | --- |
| `KeenableClient` | `POST /v1/search/public` when keyless, `POST /v1/search` with a key | `X-API-Key` (optional — the keyless endpoint is rate-limited) |
| `ExaClient` | `POST https://api.exa.ai/search` | `x-api-key` (required) |

```python
import asyncio
from keenbench.shared.search import KeenableClient, ExaClient

async def go():
    kb = KeenableClient()                    # or KeenableClient(api_key=...)
    results, err = await kb.search("who is the mayor of austin", num_results=10)
    await kb.aclose()
    return results

asyncio.run(go())
```

Each client caps in-flight requests via `max_concurrency` (default 8) — a
per-client semaphore — so a fan-out over many queries won't overwhelm the API
or your connection pool: `KeenableClient(max_concurrency=4)`.

Add an engine by subclassing `HttpSearchClient` (lazy connection reuse +
`aclose` + concurrency limiter + JSON error mapping) and mapping its response to
`SearchResult`.

## Ranking eval (RBP@5)

`keenbench.shared.judge` + `keenbench.shared.metrics` + the `keenbench rankeval`
CLI score how well a search engine ranks results for a query:

- **Judge** — a no-query-descriptor LLM relevance judge (Google "Needs Met"
  0–4 framework, ported from the internal eval), run through OpenRouter. The
  default judge model is `google/gemini-3-flash-preview`
  (`--judge-model` / `$KEENBENCH_JUDGE_MODEL`).
- **RBP@5** — Rank-Biased Precision (`p=0.8`), gain `{4:1.0, 3:0.667, 2:0.117}`,
  ceiling `1 - p^5 ≈ 0.672`. (Plain gain-weighted RBP; the internal SQL kernel's
  domain-redundancy penalties are not applied here.)

```bash
keenbench freshstream run --out fresh.jsonl
keenbench rankeval run --queries fresh.jsonl --limit 20 --engines keenable,exa --out rbp.json
```

The keyless Keenable endpoint is burst-rate-limited, so `KeenableClient`
defaults to low concurrency when used without a key; `--exa-concurrency`
(default 4) throttles Exa in a run.

**First numbers** (20 fresh RSS-derived queries, top-5, snippet-only judging,
judge `gemini-3-flash-preview`): **Exa 0.578** vs **Keenable 0.503** (ceiling
0.672; both engines 0 search/judge errors). Small sample and snippet-only (no
full-page fetch) — directional, not a headline metric.

## Development

```bash
uv sync
uv run pytest              # unit tests are deterministic and need no network
```

## Notes

- Publishing a list of public feed URLs is fine, but honor each publisher's ToS,
  `robots.txt`, and rate limits. The seed list is user-overridable and implies
  no endorsement.
- LLM keys are read only from the environment / explicit config.

## License

MIT — see [LICENSE](LICENSE).
