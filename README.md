# keenbench

[![CI](https://github.com/keenableai/keenbench/actions/workflows/ci.yaml/badge.svg)](https://github.com/keenableai/keenbench/actions/workflows/ci.yaml)

Search/retrieval benchmarks from [Keenable.ai](https://keenable.ai). A
benchmark is a query set plus a scoring method; each is a module under
`keenbench` with the same two subcommands:

```bash
keenbench <benchmark> generate ... --out queries.jsonl   # produce query rows (JSONL)
keenbench <benchmark> run --queries queries.jsonl ...    # evaluate engines on them (JSON report)
```

| Benchmark | Queries | Scoring |
| --- | --- | --- |
| [`freshstream`](#freshstream) | fresh, time-sensitive queries from live RSS + Google Trends | LLM relevance judge → RBP@5 |
| [`companyfill`](#companyfill) | company & financial fact lookups grounded in public registries and SEC filings | answer-recall@K + MRR@K, deterministic (optional LLM backstop) |
| [`scholar`](#scholar) | known-item paper retrieval: by title vs. by a full-text-only detail | recall@K + MRR@K by paper-id match |
| [`legal`](#legal) | known-item caselaw / CFR retrieval | recall@K + MRR@K by citation/docket/URL identity |
| [`findallmcp`](#findallmcp) | distribution questions answered by an agent under a dollar budget, comparing MCP search backends | set recall/precision + stat accuracy vs registry gold |

Gold is generated on demand from public sources; nothing is committed.
`rarestream` is a query producer, not a bench: it samples English rare-word
queries from a pre-filtered HF artifact and evaluates them like freshstream.

## Install

Uses [uv](https://docs.astral.sh/uv/): `uv sync`, then `uv run keenbench ...`
(or `uv tool install --editable .` for a global `keenbench`).

## Configuration

The CLI auto-loads `.env` from the working directory (copy
[`.env.example`](.env.example)); real exported variables take precedence.

| Variable | Purpose |
| --- | --- |
| `OPENROUTER_API_KEY` | all LLM work — query projection (freshstream, companyfill `filingdoc`, scholar, legal `code`) and judging |
| `EXA_API_KEY`, `SERPER_API_KEY` (`google`), `SEARCHAPI_API_KEY` (`bing`), `BRAVE_API_KEY`, `PARALLEL_API_KEY`, `TAVILY_API_KEY`, `PERPLEXITY_API_KEY`, `OCTEN_API_KEY`, `CERAMIC_API_KEY`, `YOU_API_KEY` | one per engine, required when that engine is in `--engines` |
| `KEENABLE_API_KEY` | optional — without it the keyless, rate-limited endpoint is used |
| `KEENBENCH_LLM_MODEL`, `KEENBENCH_JUDGE_MODEL` | defaults `google/gemini-3.1-flash-lite`, `google/gemini-3-flash-preview`; `--llm-model` / `--judge-model` override |

All `run` commands share one interface:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--queries` | (required) | JSONL query rows, typically from `generate` |
| `--out` | `-` | report path; `-` = stdout |
| `--engines` | `keenable,exa` | comma-separated engine list |
| `--num-results` | `5` | top-K fetched and scored per engine |
| `--snippet-chars` | `500` | uniform cap on per-result evidence text (`0` = uncapped), so engines returning fatter content don't get free evidence |
| `--limit` / `--sample` / `--seed` | `0` / `stratified` / `0` | deterministic sample of N queries |
| `--judge-model` / `--judge-concurrency` | env / `8` | LLM judge knobs |

Per-engine tuning is env-based: `KEENABLE_MODE`, `EXA_CONCURRENCY`,
`PARALLEL_MODE`, `TAVILY_DEPTH`. Queries whose search or judging failed are
excluded from the mean via `num_scored` (with `search_errors` /
`judge_errors` reported) rather than scored as zero.

## freshstream

Mines what's trending right now into keyword queries; engines are scored on
how well they rank results for them.

```bash
keenbench freshstream generate --source rss --out queries.jsonl    # or --source trending
keenbench freshstream run --queries queries.jsonl --limit 20 --out rbp.json
```

`generate` feeds one cohort from two streams: **RSS** — ~124 curated public
feeds, the newest item per feed within a freshness window (1h for most feeds,
168h for papers), backfilled with the least-stale items when too few survive —
and **Google Trends** — the keyless Trends RSS across all 52 US geos, merged,
fuzzy-deduped, capped by traffic. An LLM projects each item into a query and
refuses evergreen content. `query_id` is deterministic from
`(query_text, hour_ts)`. The feed list lives in
[`feeds.default.toml`](src/keenbench/freshstream/configs/feeds.default.toml)
(override with `--feeds`; honor each publisher's ToS and rate limits).

`run` judges each unique `(query, url)` once across engines with an LLM
relevance judge (Google "Needs Met" 0–4) and scores RBP@5 (`p=0.8`, ceiling
≈ 0.672) with redundancy penalties for duplicate URLs and repeated domains.
`--snippet-chars` keeps judge evidence uniform across engines. `--queries`
also accepts plain text, one query per line.

## companyfill

Keyword queries about public companies (`"nvidia ceo"`, `"nvidia q1 fiscal
2026 net income"`) with gold answers from Wikidata, GLEIF, and SEC filings —
scored on whether top-K results *contain the answer*, not whether they hit
one pinned URL.

```bash
keenbench companyfill generate --max-companies 100 --per-company 1 --out gold.jsonl
keenbench companyfill run --queries gold.jsonl --judge --out report.json
```

Three suites (`--suites`): **`companyfill`** — registry facts per company
(ceo, founded_year, hq_country, website, employees, lei, ticker);
**`filings`** — single-quarter 10-Q facts (net income, operating income,
diluted EPS) from SEC XBRL, stratified by market cap; **`filingdoc`** —
known-item filing retrieval, gold = the accession number. ~50% of
`filings`/`filingdoc` queries carry operator syntax (`"quoted"`, `site:`,
`after:`/`before:`), tagged in `query_origin.syntax`.

Scoring is deterministic with per-field matchers: nickname-tolerant person
names, 2% band for money, 15% for employee counts, country aliases,
registrable-domain match for websites, and required cue words for
low-entropy fields so a stray number can't score. `--judge` adds an LLM
backstop consulted only for rejected results ranked ahead of the first
deterministic hit — it can upgrade a miss but never revoke a hit. The report
breaks down by field, suite, syntax, cap tier, and freshness, and splits
misses into system-specific vs universal. Snippet-only checking is a lower
bound, applied symmetrically across engines.

## scholar

Known-item paper retrieval. Each paper yields a **`title`** query (degraded
title, answerable from metadata) and a **`body`** query (a full-text-only
detail, machine-verified absent from title and abstract) — the gap between
the two is the point.

```bash
keenbench scholar generate --age-buckets 7d,30d,1y --per-cell 10 --out gold.jsonl
keenbench scholar run --queries gold.jsonl --num-results 10 --out report.json
```

Gold comes from arXiv and Europe PMC, paired and balanced over
`(domain × age)` cells. Scoring is deterministic: result URLs and snippets
are scanned for arXiv ids, DOIs, and PMIDs; a query is a hit when an id
matches the gold paper. The report separates title vs body recall
(`by_bucket`) and splits misses into system-specific vs universal. Pages
with no inline identifier can't match, so recall is a lower bound, applied
symmetrically.

## legal

Known-item legal retrieval; gold is a document identity from the citation
graph, so no expert annotation is needed. ~50% of queries carry operator
syntax.

```bash
keenbench legal generate --per-court 4 --per-title 4 --out legal.jsonl
keenbench legal run --queries legal.jsonl --out legal.json
```

Two suites (`--suites`): **`caselaw`** — recent published opinions from the
CourtListener API across 14 federal courts, one caption-style query per case
(gold: reporter citations, docket + party tokens, cluster id); **`code`** —
eCFR sections projected by an LLM into a query about the section's substance
with one verbatim quoted span, rejected if it leaks the citation (gold: the
`title CFR section` citation). `run` scans result URLs and snippets for
reporter citations, docket numbers (scored only alongside a gold party
token), CourtListener/Justia URLs, and CFR citations; breakdowns by suite,
syntax, and court.

## findallmcp

Agentic — measures the thesis of
[The Minimum Experiment](https://keenable.ai/blog/the-minimum-experiment):
every task asks for a distribution ("find all X", "what fraction of X") whose
ground truth comes from a structured public registry, so an agent reasoning
from priors or a few top documents scores measurably worse than one that
actually holds the population.

```bash
keenbench findallmcp generate --out findallmcp.jsonl
keenbench findallmcp run --queries findallmcp.jsonl --backends keenable,webql \
  --budget-usd 1.0 --out findallmcp.json
```

Six suites (`--suites` picks a subset), gold computed at generate time from
the registry that scores the task; enumerate gold sets land at 8–40 entries
via auto-picked thresholds: **`hn`** (Show HN launches via the keyless
Algolia API: enumerate plus count and digit-fraction stats), **`edgar`** (SEC
full-text search over curated 8-K phrases, plus an S-1 count), **`fedreg`**
(EPA final-rule count over 30 days via the Federal Register API),
**`github`** (repos created over 30 days, star-thresholded, plus a ≥300-star
count), **`cpsc`** (consumer product recalls via the keyless saferproducts.gov
API, window-thresholded, plus a count), and **`awards`** (US federal contract
recipients over an auto-picked obligated-dollar threshold via the keyless
USAspending API). Suites are chosen so no single open-web page
enumerates the population — the answer must be assembled from scattered
coverage. Each suite's registry endpoints are blocked in the agent's tool
path (`BLOCKED_REGISTRIES` in `harness.py`) so answers must come from
open-web search, not from re-querying the gold source.

`run` drives an LLM agent (default `anthropic/claude-sonnet-5`;
`--agent-model` / `KEENBENCH_AGENT_MODEL`) with the tools of one MCP backend
at a time — `keenable` (stdio, `npx -y @keenable/mcp`), `webql` (hosted, adds
map/reduce/view distribution tools), `exa`, `parallel` — under a hard dollar
budget per task: LLM tokens at list prices plus a per-tool price table, spend
shown to the agent after every tool result, a forced answer once the budget
crosses. Scoring is deterministic: enumerations match gold entities by
normalized name (aliases included) or URL domain (recall/precision/F1);
stats score `max(0, 1 − relative error)`. `--budget-usd` accepts a comma
list, nesting
summaries under `by_budget`. Agent runs are nondeterministic and paid —
compare means over repeats.

## Shared infrastructure

`keenbench.shared.search` — a `SearchClient` protocol (errors-as-data
`async search(query, *, num_results) -> (results, error)`) with clients for
every engine above. Google-style operators (`site:`, `after:`, `before:`)
are parsed out and translated per engine to its best native mechanism;
unsupported ones are dropped rather than sent as literal tokens. Adding an
engine: subclass `HttpSearchClient`, map its response to `SearchResult`, add
an `EngineSpec` to `ENGINES` in
[`factory.py`](src/keenbench/shared/search/factory.py), set the key env var —
reports and the dashboard pick it up automatically.

`keenbench.shared.agent` — the self-contained tool-calling agent behind
findallmcp: an `Agent` loop with optional planning and context compaction,
`mcp_tools_from_session` to bridge MCP tools, `RunBudget` for hard dollar
budgets.

Pipelines are pure (inputs + clients in, rows/reports out), so they also
drive from a notebook or scheduler: the ranking harness is
`keenbench.shared.rankeval.run_rbp`, the recall scorer
`keenbench.companyfill.score.run_answers`.

## Continuous benchmarks

[`bench.yaml`](.github/workflows/bench.yaml) runs against all registered
engines: freshstream hourly (`--limit 20`); daily with fresh gold —
companyfill 00:17 UTC (`--limit 120 --judge`), rarestream 06:17
(`--limit 100`), scholar 12:17 (`--per-cell 7`), legal 18:17. findallmcp is
manual dispatch only (it spends agent budget). Each run appends summary rows
(`history.jsonl`), engine-pair URL overlap (`overlap.jsonl`), and per-engine
unique-URL counts (`uniqueness.jsonl`) to `gh-pages`, rendered as a dashboard
at <https://super-journey-4z52474.pages.github.io/>, and archives full
artifacts to the HF dataset
[`keenable-ai/keenbench-results`](https://huggingface.co/datasets/keenable-ai/keenbench-results).
Needs repo secrets `OPENROUTER_API_KEY`, `HF_TOKEN`, and the per-engine keys.

## Development

```bash
uv sync
uv run pytest   # deterministic, no network
```

## License

MIT — see [LICENSE](LICENSE).
