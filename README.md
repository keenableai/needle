# keenbench

[![CI](https://github.com/keenableai/keenbench/actions/workflows/ci.yaml/badge.svg)](https://github.com/keenableai/keenbench/actions/workflows/ci.yaml)

A collection of search/retrieval benchmarks and query-stream generators from
[Keenable.ai](https://keenable.ai). Each benchmark is a self-contained module
under the `keenbench` package, exposed as a `keenbench <benchmark>` subcommand.

| Module | What it does | Status |
| --- | --- | --- |
| [`freshstream`](#freshstream) | Mine live RSS (and, soon, Google Trends) and project each item into a fresh, terse search query | RSS path shipped |
| [`companyfill`](#companyfill) | Generate company fact-lookup queries with registry-grounded gold answers, then score engines on answer-recall@K | Shipped |

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
2. **Google Trends** (`query_origin.bucket = "trending"`) — fan out over the
   keyless Google Trends RSS feed (`trends.google.com/trending/rss?geo=...`)
   for all 52 US geos (`--geos` to override), merge topics across geos with
   geo tracking, collapse fuzzy near-duplicates (highest volume wins), drop
   non-ASCII topics, cap by approximate traffic, project each survivor into a
   query via an LLM (same `NO_NEWS_EVENT` refusal), and fuzzy-dedup the
   generated queries. Keyless — no API key beyond the LLM. (A `TrendsProvider`
   protocol leaves room for a SearchAPI adapter for those with a key.)

### Run

Projection goes through [OpenRouter](https://openrouter.ai) (OpenAI-compatible),
so a single key reaches Claude, GPT, Gemini and others. The CLI auto-loads a
`.env` from the working directory (copy [`.env.example`](.env.example)); a real
exported variable takes precedence.

```bash
cp .env.example .env    # then set OPENROUTER_API_KEY
# default model is google/gemini-3.1-flash-lite; override with --llm-model or $KEENBENCH_LLM_MODEL
keenbench freshstream run --source rss --out queries.jsonl
keenbench freshstream run --source trending --out trending.jsonl   # all 52 US geos; --geos US,US-CA to narrow
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

llm = OpenRouterClient(api_key="sk-or-...", model="google/gemini-3.1-flash-lite")
hour_ts = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
rows, stats = asyncio.run(run_rss(SEED_SOURCES, llm, hour_ts=hour_ts))
```

Any object with an errors-as-data
`async complete(prompt, *, max_tokens, reasoning_effort) -> (text, error)`
method satisfies the `LLMClient` protocol.

## companyfill

An enrichment-style benchmark: keyword queries about public companies
(`"nvidia ceo"`, `"apple revenue fiscal year 2025"`) whose gold answers come
from public registries, scored by whether an engine's top-K results *contain
the answer* — not whether they hit one pinned gold URL, so any page that
actually answers gets credit. Gold is generated on demand from public APIs
(Wikidata CC0, SEC public domain, GLEIF CC0); nothing is committed. Adapted
from the public-registry core of Keenable's internal enrichment bench.

Two suites, one query row per grounded field:

- **`companyfill`** — SEC `company_tickers.json` seeds the companies; each is
  resolved to Wikidata (gated on company-class or LEI/exchange signals) and
  every grounded field becomes a query: ceo (P169 with no end date),
  founded_year, hq_country, industry, website, employees (omitted when
  Wikidata's latest figure is stale), lei (P1278, or GLEIF with
  `--use_gleif`), ticker. Companies with fewer than 4 grounded fields are
  dropped as likely mis-resolutions.
- **`financials`** — SEC XBRL companyfacts (authoritative and fresh): latest
  annual revenue, net income, total assets, stockholders' equity, with the
  fiscal year pinned in the query text so the gold is unambiguous.

```bash
keenbench companyfill generate --limit 200 --out gold.jsonl
keenbench companyfill run --queries gold.jsonl --engines keenable,exa --out report.json
```

Scoring is deterministic by default — no LLM judge. Each result's title + snippet
(capped uniformly at `--snippet_chars`, default 500, so engines returning
fatter content don't get free evidence) is checked for the gold value with
per-field-type matchers: person names tolerate nicknames (Tim ~ Timothy) via
surname + given-name-prefix matching, money matches within a 2% band
(`$416.16 billion` ≈ `416161000000`), employee counts within 15%, countries
match alias surface forms (`US`, `U.S.`, `United States of America`),
websites match the result URL's registrable domain, tickers/LEIs match
case-sensitively on word boundaries. Low-entropy fields (founded_year,
employees, ticker) additionally require a cue word (`founded`, `employees`,
`ticker`, …) in the text so a stray number can't score.

`--judge` adds an LLM backstop (OpenRouter, same judge-model knobs as
rankeval) for the deterministic matcher's blind spots — paraphrases, odd
formatting, cue words the snippet skipped. It is only consulted for results
the containment check rejected *ranked ahead of the first deterministic hit*,
so it can upgrade a miss (or improve a rank) but never revoke a deterministic
hit, and most results cost no LLM calls at all. The report tracks
`judge_upgrades` and `judge_errors`; a query whose miss might be a judge
failure (judge errored, no hit found) is excluded from `num_scored` rather
than counted as a miss.

The report gives per-engine **answer-recall@K** and **MRR@K** over queries
whose search succeeded (errors are excluded via `num_scored`, not scored as
zero), plus breakdowns by field, by suite, and by freshness cadence (`1y`
fields like ceo/revenue vs `static` ones like founded_year). Snippet-only
checking is a *lower bound* on true answer presence — comparable across
engines, not an absolute coverage number. Known caveat: ceo/employees gold
comes from Wikidata, so a stale registry entry can mark a correct fresh
answer wrong; the `financials` suite has no such gap. `--limit N` takes a
deterministic stratified sample across gold fields (`--sample uniform|head`,
`--seed`).

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

- **Judge** — an LLM relevance judge (Google "Needs Met" 0–4 framework, ported
  from the internal eval) that infers intent straight from the query text, run
  through OpenRouter. The default judge model is `google/gemini-3-flash-preview`
  (`--judge-model` / `$KEENBENCH_JUDGE_MODEL`).
- **RBP@5** — Rank-Biased Precision (`p=0.8`), gain `{4:1.0, 3:0.667, 2:0.117}`,
  ceiling `1 - p^5 ≈ 0.672`, with the internal SQL kernel's redundancy
  penalties applied per query: duplicate URL −4, third-plus result from a
  domain −2, second −1 (floored at 0; `site:` queries exempt).

```bash
keenbench freshstream run --out fresh.jsonl
keenbench rankeval run --queries fresh.jsonl --limit 20 --engines keenable,exa --out rbp.json
```

The keyless Keenable endpoint is burst-rate-limited, so `KeenableClient`
defaults to low concurrency when used without a key; set `$KEENABLE_API_KEY` to
use the authenticated endpoint at higher concurrency. `--exa-concurrency`
(default 4) throttles Exa in a run.

Exa's full page text vs Keenable's short snippets hands the judge asymmetric
evidence (the Needs-Met rubric caps thin-content documents at 2/SM), so
rankeval requests Exa highlights capped at ~500 chars by default
(`--exa-highlight-chars`, 0 restores full text).

Queries whose search failed or that have any missing judgement are excluded
from `mean_rbp_at_5` (reported via `num_scored`, `search_errors`,
`judge_errors`) rather than scored as zero, so transient API failures don't
skew the engine comparison. Each unique `(query, url)` pair is judged once
across all engines (`judged_pairs` in the report), the judge's "Today's date"
comes from each query row's `hour_ts` when present, and `--limit N` takes a
deterministic stratified sample across `topical_domain` (`--sample
uniform|head` for the alternatives, `--seed` to vary it).

**First numbers** (20 fresh RSS-derived queries, top-5, snippet-only judging,
judge `gemini-3-flash-preview`): **Exa 0.578** vs **Keenable 0.503** (ceiling
0.672; both engines 0 search/judge errors). Small sample, snippet-only (no
full-page fetch), and measured before redundancy penalties and cross-engine
judging landed — directional, not a headline metric.

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
