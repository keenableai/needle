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
| [`companyfill`](#companyfill) | Company & financial fact-lookups: registry-grounded facts, quarterly SEC-XBRL facts (`filings`), and known-item SEC-filing retrieval (`filingdoc`); ~50% of `filings`/`filingdoc` queries use operator syntax | Answer-recall@K and MRR@K, deterministic (optional LLM backstop) |
| [`scholar`](#scholar) | Known-item paper retrieval — find a specific paper by its title vs. by a full-text-only detail | Recall@K and MRR@K by paper-ID match, deterministic (no judge) |
| [`legal`](#legal) | Legal known-item retrieval — find a specific court opinion (caption) or CFR section (substance); ~50% of queries use operator syntax | Recall@K and MRR@K by citation/docket/URL identity, deterministic (no judge) |
| [`findallmcp`](#findallmcp) | Distribution questions ("find all X", "what fraction of X") answered by an agent under a dollar budget, comparing MCP search backends | Set recall/precision and stat accuracy vs registry gold, deterministic |

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
| `OPENROUTER_API_KEY` | `freshstream generate`, `freshstream run`, `companyfill generate` (filingdoc suite) + `run --judge`, `scholar generate`, `legal generate` (code suite) | One [OpenRouter](https://openrouter.ai) key reaches Claude, GPT, Gemini, … |
| `EXA_API_KEY` | the `exa` engine | Required when `--engines` includes `exa` |
| `KEENABLE_API_KEY` | the `keenable` engine | Optional — without it the keyless (rate-limited) endpoint is used |
| `SERPER_API_KEY` | the `google` engine | [Serper](https://serper.dev) Google SERP API |
| `SEARCHAPI_API_KEY` | the `bing` engine | [SearchAPI](https://www.searchapi.io) |
| `BRAVE_API_KEY` | the `brave` engine | [Brave Search API](https://brave.com/search/api/) |
| `PARALLEL_API_KEY` | the `parallel` engine | [Parallel](https://parallel.ai) v1 search |
| `TAVILY_API_KEY` | the `tavily` engine | [Tavily](https://tavily.com) search |
| `PERPLEXITY_API_KEY` | the `perplexity` engine | [Perplexity](https://docs.perplexity.ai) Search API |
| `OCTEN_API_KEY` | the `octen` engine | [Octen](https://octen.ai) search |
| `CERAMIC_API_KEY` | the `ceramic` engine | [Ceramic](https://docs.ceramic.ai) search |
| `KEENBENCH_LLM_MODEL` | query projection | Default `google/gemini-3.1-flash-lite`; `--llm-model` overrides |
| `KEENBENCH_JUDGE_MODEL` | judging | Default `google/gemini-3-flash-preview`; `--judge-model` overrides |

## Common `run` flags

All benchmarks' `run` commands share one interface:

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
added: `KEENABLE_MODE` (default `pro`), `EXA_CONCURRENCY` (default `1`),
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
(`"nvidia ceo"`, `"nvidia q1 fiscal 2026 net income"`) whose gold answers come
from public registries and SEC filings, scored by whether an engine's top-K
results *contain the answer* — not whether they hit one pinned gold URL, so any
page that actually answers gets credit. Gold is generated on demand from public
APIs (Wikidata CC0, SEC public domain, GLEIF CC0); nothing is committed. Adapted
from the public-registry core of Keenable's internal enrichment bench, extended
with a WebQL survey of the published finance retrieval benchmarks (FinanceBench,
FinQA, FinSearchComp).

### Generate

```bash
keenbench companyfill generate --max-companies 100 --per-company 1 \
  --filingdoc-target 40 --out gold.jsonl
```

Three suites (`--suites`, default all), one query row per grounded field:

- **`companyfill`** — SEC `company_tickers.json` seeds the companies; each is
  resolved to Wikidata (gated on company-class or LEI/exchange signals) and
  every grounded field becomes a query: ceo (P169 with no end date),
  founded_year, hq_country, website, employees (omitted when
  Wikidata's latest figure is stale), lei (P1278, or GLEIF with
  `--use-gleif`), ticker. Companies with fewer than 4 grounded fields are
  dropped as likely mis-resolutions.
- **`filings`** — SEC XBRL companyfacts, *single-quarter* 10-Q spans (net
  income, operating income, diluted EPS; revenue off by default — republished
  everywhere, calibrated ~1.0). Companies are stratified mega/large/mid cap and
  the fiscal quarter is pinned in the query text (`"acme" q1 fiscal 2026 net
  income`). FY-annual facts were dropped as too easy.
- **`filingdoc`** — known-item *filing* retrieval. Recent 10-K/10-Q/8-K filings
  come from the SEC submissions API; an LLM projects the filing text into a
  keyword query with one verbatim quoted span, accession-leak-checked. Gold is
  the accession number, matched as an `exact_id` (see below).

~50% of `filings`/`filingdoc` queries carry search-operator syntax (`"quoted"`,
`site:`, `after:`/`before:`), cycled deterministically and tagged in
`query_origin.syntax`.

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
- websites match the result URL's registrable domain; short exact ids
  (tickers) match case-sensitively on word boundaries, while long exact ids
  (LEIs, `filingdoc` accession numbers) match as a normalized substring of the
  result text *and URL* — SEC result URLs embed the accession
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

Every suite — registry facts, quarterly `filings`, and `filingdoc` identity —
is scored through this one path (`run_answers`): `filingdoc` is just an
`exact_id` field, so there is no separate scorer. The report gives per-engine
**answer-recall@K** and **MRR@K**, plus breakdowns by field, by suite
(`by_bucket`), by operator syntax (`by_syntax`), by cap tier (`by_tier`), and by
freshness cadence, along with a system-specific vs. universal miss split.
Caveats: snippet-only checking is a *lower bound* on true answer presence —
comparable across engines, not an absolute coverage number — and ceo/employees
gold comes from Wikidata, so a stale registry entry can mark a correct fresh
answer wrong (the SEC-sourced `filings`/`filingdoc` suites have no such gap).

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
**recall@K** and **MRR@K**, and — since the two query sets measure different
things — reports the **title** and **body** query sets separately via the
`by_bucket` breakdown (alongside by suite / age / domain). Title recall is
metadata-answerable known-item retrieval; body recall needs a full-text index.
A **misses** split reports `system-specific` (another engine found it →
ranking/indexing gap) vs `universal` (nobody found it → likely stale/unfindable
gold). It shares the common `run` flags; the judge flags don't apply (there is
no judge).

Caveats: this is *known-item* retrieval, so an engine that returns a
different-but-relevant paper scores a miss — that's correct for "find this
paper," not a measure of scholarly-search quality. Publisher landing pages that
carry no inline identifier (ScienceDirect PII, Nature short-form) yield no
extractable id, making recall a *lower bound*, applied symmetrically across
engines. The title-specificity gate that drops too-generic titles at generation
is a *lexical* heuristic (distinctive token — acronym / digit / camelCase /
hyphenated compound — or enough content words), so a generic-but-acronymed title
can still slip through and a distinctive short all-lowercase one can be dropped.
And the keyless `keenable` endpoint returns degraded results under the burst
load of a full run, so a batch number undercounts it — score it with a
`KEENABLE_API_KEY`, or pin the raw results, before comparing.

## legal

Legal search across two task suites, adapted from the citation-gold methodology
of the public legal-IR benchmarks (CLERC, LePaRD, BSARD): gold is a *document
identity* derived from the citation graph, so no expert annotation is needed
and `run` is free (no judge). A deliberate design point — shared with the
[`companyfill`](#companyfill) `filings`/`filingdoc` suites — is **operator
syntax coverage**: roughly half the
queries carry a search operator (`"quoted phrase"`, `site:`,
`after:`/`before:` date filters), tagged per row in `query_origin.syntax`, so
the report separates how engines handle advanced query language (`by_syntax`)
from plain keyword retrieval.

### Generate

```bash
keenbench legal generate --per-court 4 --per-title 4 --out legal.jsonl
```

Two suites (`--suites`, default both):

- **`caselaw`** — known-item *case* retrieval. Recent published opinions are
  sampled from the CourtListener search API (public domain, keyless; set
  `COURTLISTENER_API_TOKEN` to raise rate limits) across 14 federal courts
  (`--courts`) and the last `--months-back` months, spread over monthly
  windows. Each case yields one caption-style query (party names with legal
  suffixes and docket-annotation noise stripped, plus a court phrase). Gold
  identity is the case's reporter citations, docket number + party tokens, and
  CourtListener cluster id.
- **`code`** — known-item *regulation* retrieval. Sections are sampled from
  the eCFR API across 10 CFR titles (`--titles`), and an LLM projects each
  section's full text into a keyword query about the section's *substance*
  with exactly one distinctive span quoted verbatim — rejected if it leaks the
  citation (section/part/title number, "CFR", "§") or if the quoted span is
  not actually verbatim. Needs `OPENROUTER_API_KEY`. Gold identity is the
  `title CFR section` citation.

### Run (recall@K / MRR@K)

```bash
keenbench legal run --queries legal.jsonl --engines keenable,exa --out legal.json
```

Each result's URL and snippet are scanned for legal identities — reporter
citations (`89 F.4th 1188`), docket numbers (scored only alongside a gold
party token, so a bare `25-2462` can't false-positive), CourtListener/Justia
URL patterns, and CFR citations in text or cornell/ecfr URLs. The report
gives per-engine recall@K and MRR@K with `by_bucket` (suite), `by_syntax`,
and `by_court` breakdowns plus the system-specific vs universal misses split.
Identity extraction is pattern-based, so a page that discusses the case
without citing it doesn't count — recall is a lower bound, applied
symmetrically across engines.

## findallmcp

Measures the thesis of
[The Minimum Experiment](https://keenable.ai/blog/the-minimum-experiment): a
model hands you the *mode*, a search API hands you *documents*, and the wins
live in the *distribution*. Every task asks for a distribution — an exhaustive
enumeration ("find all X") or a population statistic ("what fraction of X") —
whose ground truth is computed from a structured public registry, so an agent
that reasons from priors or from a few top documents scores measurably worse
than one that actually holds the population.

Unlike the other benches this one is **agentic**: `run` drives an LLM agent
(default `anthropic/claude-sonnet-4.5` via OpenRouter, `--agent-model` /
`KEENBENCH_AGENT_MODEL` to override) with the tools of one MCP search backend
at a time, under a hard **dollar budget** per task, and compares backends on
what they let the same agent find per dollar.

### Generate

```bash
keenbench findallmcp generate --out findallmcp.jsonl
```

Two suites, gold computed at generate time from the registry that scores the
task:

- **`hn`** — Show HN launches via the keyless Algolia API: one enumerate task
  (all launches over a point threshold auto-picked so the gold set lands at
  8–40 entries) and two stat tasks (population count, fraction of titles
  containing a digit).
- **`edgar`** — SEC full-text search: enumerate tasks over curated 8-K phrases
  ("material cybersecurity incident", "reverse stock split", …) that yield
  8–40 distinct filers, plus an S-1 filer-count stat task.

### Run (set recall / stat accuracy per dollar)

```bash
keenbench findallmcp run --queries findallmcp.jsonl --backends keenable,webql \
  --budget-usd 0.25 --out findallmcp.json
```

Backends are MCP servers:

- **`keenable`** — the classic search MCP (`npx -y @keenable/mcp`,
  stdio; `KEENBENCH_KEENABLE_MCP_CMD` overrides the command):
  `search_web_pages` + `fetch_page_content`.
- **`webql`** — the hosted WebQL MCP (`https://webql.keenable.ai/mcp`,
  streamable HTTP, `X-API-Key` from `KEENABLE_API_KEY`;
  `KEENBENCH_WEBQL_MCP_URL` overrides): search plus
  map/reduce/view over result sets — the distribution tools.
- **`exa`** — Exa's hosted MCP (`https://mcp.exa.ai/mcp`, key from
  `EXA_API_KEY`; `KEENBENCH_EXA_MCP_URL` overrides): `web_search_exa` +
  `web_fetch_exa`.
- **`parallel`** — Parallel's hosted Search MCP
  (`https://search.parallel.ai/mcp`, `x-api-key` from `PARALLEL_API_KEY`;
  `KEENBENCH_PARALLEL_MCP_URL` overrides): `web_search` + `web_fetch`.

The harness runs on the shared
[tool-calling agent](#tool-calling-agent) (`keenbench.shared.agent`), with
each backend's MCP session bridged into the agent's tool registry per task.
The budget is charged in dollars via its `RunBudget`: LLM tokens at list
prices plus a per-call price table for each tool (`models.py`;
`map_result_set_with_llm` costs 10× a plain search, so WebQL's heavier tools
aren't free). The agent sees its running spend after every tool result and is
forced to answer once the budget is crossed (overshoot is bounded by one turn
and reported in `spent_usd`).

Scoring is deterministic: enumerate answers are matched to gold entities by
normalized name (legal suffixes and "Show HN:" stripped) or URL domain →
recall/precision/F1; stat answers score `max(0, 1 - relative error)`, with a
per-task tolerance flag (`within_tol`) reported alongside. The report gives
per-backend `mean_score`, `set_recall`/`set_precision`, `stat_score`,
`stat_within_tol`, `mean_spent_usd`, `mean_tool_calls`, and `by_suite` /
`by_bucket` breakdowns. Caveats: agent runs are nondeterministic and paid —
run with small task counts and compare means over repeats; entity matching is
lexical, so an agent naming a company by an unusual alias can be undercounted
(applied symmetrically across backends).

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
| `SerperClient` | `POST https://google.serper.dev/search` (the `google` engine) | `X-API-KEY` (required) |
| `SearchApiClient` | `GET https://www.searchapi.io/api/v1/search` — wraps Bing (the `bing` engine) | `Authorization: Bearer` (required) |
| `BraveClient` | `GET https://api.search.brave.com/res/v1/web/search` | `X-Subscription-Token` (required) |
| `ParallelClient` | `POST https://api.parallel.ai/v1/search` | `x-api-key` (required) |
| `TavilyClient` | `POST https://api.tavily.com/search` | `Authorization: Bearer` (required) |
| `PerplexityClient` | `POST https://api.perplexity.ai/search` | `Authorization: Bearer` (required) |
| `OctenClient` | `POST https://api.octen.ai/search` | `X-Api-Key` (required) |
| `CeramicClient` | `POST https://api.ceramic.ai/search` | `Authorization: Bearer` (required) |

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
semaphore (default 8). `CeramicClient` additionally truncates queries to
the API's 50-word limit and clamps `--snippet-chars` into its
`maxDescriptionLength` range of `[1000, 8000]`.

### Query operators

Bench queries carry Google-style operators (`site:host`,
`after:YYYY-MM-DD`, `before:YYYY-MM-DD`). Mirroring keenable's
orchestrator, `queryops.parse_ops` extracts them and each client
translates to its engine's best native mechanism — operators the engine
parses natively stay in the query text, translated ones are stripped from
it, and unsupported date bounds are dropped rather than sent as literal
tokens:

| Engine | `site:` | `after:` / `before:` |
| --- | --- | --- |
| `google`, `bing` | in query text (native) | in query text (native) |
| `keenable` | in query text (native) | rewritten to `published_after:` / `published_before:` (native) |
| `brave` | in query text (native) | `freshness=YYYY-MM-DDtoYYYY-MM-DD` (open ends filled with epoch/today) |
| `exa` | `includeDomains` | `startPublishedDate` / `endPublishedDate` |
| `tavily` | `include_domains` | `start_date` / `end_date` |
| `perplexity` | `search_domain_filter` | `search_after_date_filter` / `search_before_date_filter` |
| `parallel` | `source_policy.include_domains` | dropped (no API support) |
| `octen` | `include_domains` | `start_time` / `end_time` |
| `ceramic` | dropped (no API support; a literal `site:` token returns zero results) | dropped (no API support) |

Malformed operator values (`after:yesterday`, `site:` with no host) stay
in the query text untouched. The judge still rates results against the
original operator-bearing query, so an engine whose native filter is weak
is penalized the same as before.

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

### Tool-calling agent

`keenbench.shared.agent` is a self-contained tool-calling agent for agentic
benches: an `Agent` loop (tool-calling turns, optional planning step,
context compaction, best-effort summary on max steps) over the shared
`OpenRouterClient`'s `chat()` (OpenAI-style tools +
token usage). `mcp_tools_from_session` bridges an MCP session's tools into
the agent's `Tool` registry. An optional `RunBudget` enforces a hard dollar
budget per run — LLM tokens at caller-supplied prices plus a per-tool price
callable, running spend injected after every tool turn, and a forced final
answer once the budget crosses. `chat()` retries transient OpenRouter
failures (429/5xx/transport) with exponential backoff:

```python
from keenbench.shared.agent import Agent, RunBudget, Tool
from keenbench.shared.llm import OpenRouterClient

llm = OpenRouterClient(api_key="sk-or-...", model="anthropic/claude-sonnet-4.5", timeout_s=180.0)
agent = Agent(llm, tools, system_prompt, max_steps=20)
budget = RunBudget(limit_usd=0.25, in_price_per_mtok=3.0, out_price_per_mtok=15.0,
                   tool_cost=lambda name: 0.005)
result = await agent.run(task_prompt, budget=budget)
```

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
against all registered engines: freshstream hourly (`--limit 20`), and
companyfill + scholar + rarestream + legal daily at 00:17 UTC (fresh gold each
— companyfill regenerates all three suites and runs `--limit 120` with the
`--judge` backstop, scholar `--per-cell 7`). Each run:

- appends summary rows to `data/history.jsonl` and per-engine-pair URL-overlap
  rows (mean Jaccard of normalized top-K URL sets per query) to
  `data/overlap.jsonl` on the `gh-pages` branch — rendered as a dashboard
  (trends, latest tiles, per-field table, an all-time engine-overlap matrix,
  judgement browser) at <https://super-journey-4z52474.pages.github.io/> (the
  URL becomes `keenableai.github.io/keenbench` when the repo goes public);
- archives the full artifacts (reports with per-result judge reasoning, the
  generated queries, the gold) to the public HF dataset
  [`keenable-ai/keenbench-results`](https://huggingface.co/datasets/keenable-ai/keenbench-results)
  under `runs/<utc-hour>/`, which the dashboard's judgement browser reads.

Needs repo secrets: `OPENROUTER_API_KEY`, `HF_TOKEN`, and the per-engine keys
listed under [Configuration](#configuration) (`KEENABLE_API_KEY` optional).

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
