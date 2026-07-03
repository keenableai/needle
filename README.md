# keenbench

[![CI](https://github.com/keenableai/keenbench/actions/workflows/ci.yaml/badge.svg)](https://github.com/keenableai/keenbench/actions/workflows/ci.yaml)

Search/retrieval benchmarks from [Keenable.ai](https://keenable.ai).

A benchmark is a query set plus a scoring method. Each one is a self-contained
module under the `keenbench` package with the same two subcommands:

```bash
keenbench <benchmark> generate ... --out queries.jsonl   # produce query rows (JSONL)
keenbench <benchmark> run --queries queries.jsonl ...    # evaluate engines on them (JSON report)
```

| Benchmark | Queries | Metric |
| --- | --- | --- |
| [`freshstream`](#freshstream) | Fresh, time-sensitive queries mined from live RSS and Google Trends | LLM relevance judge → RBP@5 |
| [`companyfill`](#companyfill) | Company fact-lookups with registry-grounded gold answers | Answer-recall@K and MRR@K, deterministic (optional LLM backstop) |
| [`scholar`](#scholar) | Known-item paper retrieval — find a specific paper by its title vs. by a full-text-only detail | Recall@K and MRR@K by paper-ID match, deterministic (no judge) |

Everything engine- or judge-related is shared infrastructure in
[`keenbench.shared`](#shared-infrastructure) — search clients, LLM client,
relevance judge, metrics, sampling, and the RBP ranking pipeline — not a
benchmark of its own.

## Install

Uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

This installs the `keenbench` command into the project venv — invoke it as
`uv run keenbench ...` (or activate the venv first and drop the prefix; the
examples below assume one of the two). To get a global `keenbench` on your
PATH instead: `uv tool install --editable .`

## Configuration

The CLI auto-loads a `.env` from the working directory (copy
[`.env.example`](.env.example)); a real exported variable takes precedence.
Keys are read only from the environment.

| Variable | Needed for | Notes |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | `freshstream generate`, `freshstream run`, `companyfill run --judge`, `scholar generate` | One [OpenRouter](https://openrouter.ai) key reaches Claude, GPT, Gemini, … |
| `EXA_API_KEY` | the `exa` engine | Required when `--engines` includes `exa` |
| `KEENABLE_API_KEY` | the `keenable` engine | Optional — without it the keyless (rate-limited) endpoint is used |
| `SEARCHAPI_API_KEY` | the `google` and `bing` engines | One [SearchAPI](https://www.searchapi.io) key covers both |
| `BRAVE_API_KEY` | the `brave` engine | [Brave Search API](https://brave.com/search/api/) |
| `PARALLEL_API_KEY` | the `parallel` engine | [Parallel](https://parallel.ai) v1 search |
| `TAVILY_API_KEY` | the `tavily` engine | [Tavily](https://tavily.com) search |
| `KEENBENCH_LLM_MODEL` | query projection | Default `google/gemini-3.1-flash-lite`; `--llm-model` overrides |
| `KEENBENCH_JUDGE_MODEL` | judging | Default `google/gemini-3-flash-preview`; `--judge-model` overrides |

## Common `run` flags

All three benchmarks' `run` commands share one interface:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--queries` | (required) | JSONL of query rows, typically from `generate` |
| `--out` | `-` | Report path; `-` prints to stdout |
| `--engines` | `keenable,exa` | Comma-separated engine list |
| `--num-results` | `5` | Top-K results fetched and scored per engine |
| `--snippet-chars` | `500` | Uniform cap on per-result evidence text, so engines returning fatter content don't get free evidence; `0` = uncapped |
| `--limit` / `--sample` / `--seed` | `0` / `stratified` / `0` | `--limit N` takes a deterministic stratified sample (`--sample uniform\|head` for alternatives, `--seed` to vary it) |
| `--judge-model` / `--judge-concurrency` | env / `8` | LLM judge knobs |

Per-engine tuning is env-based so the flag set stays flat as engines are
added: `KEENABLE_MODE` (default `pro`), `EXA_CONCURRENCY` (default `4`),
`PARALLEL_MODE` (default `basic`), `TAVILY_DEPTH` (default `basic`).

Error accounting is shared too: queries whose search or judging failed are
excluded from the mean via `num_scored` (with `search_errors` /
`judge_errors` reported) rather than scored as zero, so transient API
failures don't skew the engine comparison.

## freshstream

Mines what's trending *right now* and turns it into keyword-style search
queries — the kind of fast-decaying queries a search engine has to keep fresh.
Engines are then scored on how well they *rank* results for those queries.

### Generate

Two independent real-time streams feed one cohort, both tagged
`query_source = "fresh-queries"`:

- **RSS firehose** (`query_origin.bucket = "rss"`) — fetch ~124 curated public
  feeds, keep the newest item per feed inside a freshness window (1h for most
  feeds, 168h for academic papers), and project each survivor into a query via
  an LLM. Evergreen content (explainers, how-tos, reviews, opinion) is refused
  with a `NO_NEWS_EVENT` sentinel and dropped.
- **Google Trends** (`query_origin.bucket = "trending"`) — fan out over the
  keyless Google Trends RSS feed for all 52 US geos (`--geos` to override),
  merge topics across geos, collapse fuzzy near-duplicates (highest volume
  wins), drop non-ASCII topics, cap by approximate traffic, project each
  survivor into a query (same `NO_NEWS_EVENT` refusal), and fuzzy-dedup the
  results. Keyless — no API key beyond the LLM. (A `TrendsProvider` protocol
  leaves room for a SearchAPI adapter for those with a key.)

```bash
keenbench freshstream generate --source rss --out queries.jsonl
keenbench freshstream generate --source trending --out trending.jsonl   # --geos US,US-CA to narrow
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

`query_id` is deterministic from `(query_text, hour_ts)`, so re-running the
same hour produces byte-identical rows.

The built-in feed list lives in
[`src/keenbench/freshstream/configs/feeds.default.toml`](src/keenbench/freshstream/configs/feeds.default.toml)
(the single source of truth — `SEED_SOURCES` loads it at import). Copy it,
edit, and pass your version with `--feeds`:

```bash
keenbench freshstream generate --feeds my-feeds.toml --out queries.jsonl
```

### Run (RBP@5)

```bash
keenbench freshstream run --queries queries.jsonl --limit 20 --engines keenable,exa --out rbp.json
```

- **Judge** — an LLM relevance judge (Google "Needs Met" 0–4 framework, ported
  from the internal eval) that infers intent straight from the query text. The
  judge's "Today's date" comes from each row's `hour_ts` when present, and each
  unique `(query, url)` pair is judged once across all engines (`judged_pairs`
  in the report).
- **RBP@5** — Rank-Biased Precision (`p=0.8`), gain `{4:1.0, 3:0.667, 2:0.117}`,
  ceiling `1 - p^5 ≈ 0.672`, with the internal SQL kernel's redundancy
  penalties applied per query: duplicate URL −4, third-plus result from a
  domain −2, second −1 (floored at 0; `site:` queries exempt).

`--snippet-chars` matters here for fairness: Exa returns full page text while
Keenable returns short snippets, which would hand the judge asymmetric
evidence (the Needs-Met rubric caps thin-content documents at 2/SM). The cap
is applied both to Exa's highlights request and to the evidence the judge
sees, uniformly across engines. `--snippet-chars 0` restores Exa's full page
text, but the judge's evidence keeps a 50,000-char safety cap so one huge
page can't blow the judge's context window.

`--queries` also accepts plain text (one query per line), so the harness works
on any query stream, not just freshstream output.

**First numbers** (20 fresh RSS-derived queries, top-5, snippet-only judging,
judge `gemini-3-flash-preview`): **Exa 0.578** vs **Keenable 0.503** (ceiling
0.672; both engines 0 search/judge errors). Small sample, snippet-only, and
measured before redundancy penalties and cross-engine judging landed —
directional, not a headline metric.

## companyfill

An enrichment-style benchmark: keyword queries about public companies
(`"nvidia ceo"`, `"apple revenue fiscal year 2025"`) whose gold answers come
from public registries, scored by whether an engine's top-K results *contain
the answer* — not whether they hit one pinned gold URL, so any page that
actually answers gets credit. Gold is generated on demand from public APIs
(Wikidata CC0, SEC public domain, GLEIF CC0); nothing is committed. Adapted
from the public-registry core of Keenable's internal enrichment bench.

### Generate

```bash
keenbench companyfill generate --max-companies 200 --out gold.jsonl
```

Two suites (`--suites`, default both), one query row per grounded field:

- **`companyfill`** — SEC `company_tickers.json` seeds the companies; each is
  resolved to Wikidata (gated on company-class or LEI/exchange signals) and
  every grounded field becomes a query: ceo (P169 with no end date),
  founded_year, hq_country, industry, website, employees (omitted when
  Wikidata's latest figure is stale), lei (P1278, or GLEIF with
  `--use-gleif`), ticker. Companies with fewer than 4 grounded fields are
  dropped as likely mis-resolutions.
- **`financials`** — SEC XBRL companyfacts (authoritative and fresh): latest
  annual revenue, net income, total assets, stockholders' equity, with the
  fiscal year pinned in the query text so the gold is unambiguous.

### Run (answer-recall@K)

```bash
keenbench companyfill run --queries gold.jsonl --engines keenable,exa --out report.json
```

Scoring is deterministic by default — no LLM judge. Each result's title +
snippet (capped at `--snippet-chars`) is checked for the gold value with
per-field-type matchers:

- person names tolerate nicknames (Tim ~ Timothy) via surname +
  given-name-prefix matching
- money matches within a 2% band (`$416.16 billion` ≈ `416161000000`),
  employee counts within 15%
- countries match alias surface forms (`US`, `U.S.`, `United States of America`)
- websites match the result URL's registrable domain; tickers/LEIs match
  case-sensitively on word boundaries
- low-entropy fields (founded_year, employees, ticker) additionally require a
  cue word (`founded`, `employees`, `ticker`, …) in the text so a stray
  number can't score

`--judge` adds an LLM backstop for the deterministic matcher's blind spots —
paraphrases, odd formatting, cue words the snippet skipped. It is only
consulted for results the containment check rejected *ranked ahead of the
first deterministic hit*, so it can upgrade a miss (or improve a rank) but
never revoke a deterministic hit, and most results cost no LLM calls at all.
The report tracks `judge_upgrades` and `judge_errors`; a query whose miss
might be a judge failure is excluded from `num_scored` rather than counted as
a miss.

The report gives per-engine **answer-recall@K** and **MRR@K**, plus breakdowns
by field, by suite, and by freshness cadence (`1y` fields like ceo/revenue vs
`static` ones like founded_year). Caveats: snippet-only checking is a *lower
bound* on true answer presence — comparable across engines, not an absolute
coverage number — and ceo/employees gold comes from Wikidata, so a stale
registry entry can mark a correct fresh answer wrong (the `financials` suite
has no such gap).

## scholar

A **known-item retrieval** benchmark: can an engine surface *one specific
paper*? Each paper produces two queries, and the gap between how well an engine
answers them is the point:

- **`title`** — the degraded paper title. Answerable from the metadata every
  engine indexes.
- **`body`** — a distinctive detail pulled from the paper's full text (a named
  method, a precise measured value, a trial ID) that is machine-verified to be
  *absent* from the title and abstract, so only a full-text index can match it.

Scoring is deterministic identity matching — no LLM judge — so `run` is free.

### Generate

```bash
keenbench scholar generate --age-buckets 7d,30d,1y --per-cell 10 --out gold.jsonl
```

Gold is generated on demand from two public, open sources: **arXiv** (CS,
physics, life, social) and **Europe PMC** (health, full JATS body text). The set
is **paired and balanced by construction** — sampled over `(domain × age)` cells
so it comes out even across five domains and the requested age cohorts, with
exactly one `title` and one `body` query per paper. Age buckets (`7d` / `30d` /
`1y` / `older`) are sampled from narrow date bands so a paper's true publication
age matches its bucket. `generate` needs `OPENROUTER_API_KEY` for the body-query
projection (model via `KEENBENCH_LLM_MODEL` / `--llm-model`); `--per-cell N`
sets the target paired papers per cell, `--suites` restricts sources. Nothing is
committed.

Each output line is one gold query row:

```json
{
  "query_id": "…", "query_hash": "…",
  "query_text": "smoothquant activation outliers migration factor",
  "query_source": "scholar",
  "query_origin": {"bucket": "body", "suite": "arxiv", "provenance": {"title": "…", "url": "…"}},
  "gold": {"paper_key": "2506.12345", "ids": {"arxiv": "2506.12345"},
           "age_bucket": "30d", "domain": "computer science", "published_date": "…"},
  "hour_ts": "…"
}
```

### Run (recall@K / MRR@K)

```bash
keenbench scholar run --queries gold.jsonl --engines keenable,exa,brave --out report.json
```

Each result's URL and snippet are scanned for a paper identity — arXiv id, DOI,
or PMID (PMC ids are resolved to PMIDs via NCBI's converter) — and a query is a
hit when any extracted id matches the gold paper. The report gives per-engine
**recall@K** and **MRR@K**, breakdowns by bucket / suite / age / domain, a
**shallow-index rate** (share of title-found papers *missed* on their body
query — a direct read on index depth), and a **misses** split of
`system-specific` (another engine found it → ranking/indexing gap) vs
`universal` (nobody found it → likely stale/unfindable gold). It shares the
common `run` flags; the judge flags don't apply (there is no judge).

Caveats: this is *known-item* retrieval, so an engine that returns a
different-but-relevant paper scores a miss — that's correct for "find this
paper," not a measure of scholarly-search quality. Publisher landing pages that
carry no inline identifier (ScienceDirect PII, Nature short-form) yield no
extractable id, making recall a *lower bound*, applied symmetrically across
engines. And the keyless `keenable` endpoint returns degraded results under the
burst load of a full run, so a batch number undercounts it — score it with a
`KEENABLE_API_KEY`, or pin the raw results, before comparing.

## Shared infrastructure

### Search clients

`keenbench.shared.search` provides a common client interface — a
`SearchResult` (`url`, `title`, `snippet`, `published_date`, `score`, `raw`)
and a `SearchClient` protocol
(`async search(query, *, num_results) -> (results, error)`, errors-as-data,
never raises). Shipped engines:

| Client | Endpoint | Key |
| --- | --- | --- |
| `KeenableClient` | `POST /v1/search/public` when keyless, `POST /v1/search` with a key | `X-API-Key` (optional — the keyless endpoint is burst-rate-limited, so the client defaults to low concurrency without one) |
| `ExaClient` | `POST https://api.exa.ai/search` | `x-api-key` (required) |
| `SearchApiClient` | `GET https://www.searchapi.io/api/v1/search` — wraps Google and Bing (the `google` / `bing` engines) | `Authorization: Bearer` (required) |
| `BraveClient` | `GET https://api.search.brave.com/res/v1/web/search` | `X-Subscription-Token` (required) |
| `ParallelClient` | `POST https://api.parallel.ai/v1/search` | `x-api-key` (required) |
| `TavilyClient` | `POST https://api.tavily.com/search` | `Authorization: Bearer` (required) |

```python
import asyncio
from keenbench.shared.search import KeenableClient

async def go():
    kb = KeenableClient()                    # or KeenableClient(api_key=...)
    results, err = await kb.search("who is the mayor of austin", num_results=10)
    await kb.aclose()
    return results

asyncio.run(go())
```

Each client caps in-flight requests via a per-client `max_concurrency`
semaphore (default 8).

Everything downstream — the pipelines, reports, scheduled runs, and the
dashboard — is engine-count-agnostic, so adding an engine to the comparison
is three steps:

1. subclass `HttpSearchClient` (lazy connection reuse + `aclose` +
   concurrency limiter + JSON error mapping) and map its response to
   `SearchResult`;
2. add an `EngineSpec` to `ENGINES` in
   [`shared/search/factory.py`](src/keenbench/shared/search/factory.py)
   (name, API-key env var, build function);
3. put the key in the environment (a repo secret for CI) and add the name to
   `--engines` / the workflow's `ENGINES` env. The dashboard picks the new
   engine up from the data and assigns it a stable color slot automatically.

### Pipelines as a library

The pipelines are pure — inputs + clients in, rows/reports out — so they drive
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
method satisfies the `LLMClient` protocol. The ranking harness is
`keenbench.shared.rankeval.run_rbp`, the recall scorer is
`keenbench.companyfill.score.run_answers`.

## Continuous benchmarks

[`bench.yaml`](.github/workflows/bench.yaml) runs the benchmarks on a schedule
against `keenable,exa`: freshstream hourly (`--limit 20`), companyfill daily at
00:17 UTC (fresh gold, `--limit 100`). Each run:

- appends summary rows to `data/history.jsonl` on the `gh-pages` branch —
  rendered as a dashboard (trends, latest tiles, per-field table, judgement
  browser) at <https://super-journey-4z52474.pages.github.io/> (the URL becomes
  `keenableai.github.io/keenbench` when the repo goes public);
- archives the full artifacts (reports with per-result judge reasoning, the
  generated queries, the gold) to the public HF dataset
  [`keenable-ai/keenbench-results`](https://huggingface.co/datasets/keenable-ai/keenbench-results)
  under `runs/<utc-hour>/`, which the dashboard's judgement browser reads.

Needs repo secrets: `OPENROUTER_API_KEY`, `EXA_API_KEY`, `HF_TOKEN`
(`KEENABLE_API_KEY` optional).

## Development

```bash
uv sync
uv run pytest              # unit tests are deterministic and need no network
```

## Notes

- Publishing a list of public feed URLs is fine, but honor each publisher's
  ToS, `robots.txt`, and rate limits. The seed list is user-overridable and
  implies no endorsement.

## License

MIT — see [LICENSE](LICENSE).
