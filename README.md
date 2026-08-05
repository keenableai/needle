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
| [`news`](#news) | fresh, time-sensitive queries from live RSS + Google Trends | LLM relevance judge → RBP@5 |
| [`finance`](#finance) | company & financial fact lookups grounded in public registries and SEC filings | answer-recall@K + MRR@K, deterministic (optional LLM backstop) |
| [`scholar`](#scholar) | known-item paper retrieval: by title vs. by a full-text-only detail | recall@K + MRR@K by paper-id match |
| [`legal`](#legal) | known-item caselaw / CFR retrieval | recall@K + MRR@K by citation/docket/URL identity |

Gold is generated on demand from public sources; nothing is committed.
`agentic_rare` is a query producer, not a bench: it samples English rare-word
queries from a pre-filtered HF artifact and evaluates them like news.

## Install

Uses [uv](https://docs.astral.sh/uv/): `uv sync`, then `uv run keenbench ...`
(or `uv tool install --editable .` for a global `keenbench`).

## Configuration

The CLI auto-loads `.env` from the working directory (copy
[`.env.example`](.env.example)); real exported variables take precedence.

| Variable | Purpose |
| --- | --- |
| `OPENROUTER_API_KEY` | all LLM work — query projection (news, finance `filingdoc`, scholar, legal `code`) and judging |
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
| `--snippet-chars` | `2000` | uniform cap on per-result evidence text (`0` = uncapped), so engines returning fatter content don't get free evidence |
| `--limit` / `--sample` / `--seed` | `0` / `stratified` / `0` | deterministic sample of N queries |
| `--judge-model` / `--judge-concurrency` | env / `8` | LLM judge knobs |

Per-engine tuning is env-based: `EXA_CONCURRENCY`, `TAVILY_DEPTH`; Keenable's
and Parallel's modes are fixed per engine entry (`keenable` = pro,
`keenable-realtime` = realtime, `parallel` = basic, `parallel-turbo` =
turbo). Queries whose search or judging failed are
excluded from the mean via `num_scored` (with `search_errors` /
`judge_errors` reported) rather than scored as zero.

## news

Mines what's trending right now into keyword queries; engines are scored on
how well they rank results for them.

```bash
keenbench news generate --source rss --out queries.jsonl    # or --source trending
keenbench news run --queries queries.jsonl --limit 20 --out rbp.json
```

`generate` feeds one cohort from two streams: **RSS** — ~124 curated public
feeds, the newest item per feed within a freshness window (1h for most feeds,
168h for papers), backfilled with the least-stale items when too few survive —
and **Google Trends** — the keyless Trends RSS across all 52 US geos, merged,
fuzzy-deduped, capped by traffic. An LLM projects each item into a query and
refuses evergreen content. `query_id` is deterministic from
`(query_text, hour_ts)`. The feed list lives in
[`feeds.default.toml`](src/keenbench/news/configs/feeds.default.toml)
(override with `--feeds`; honor each publisher's ToS and rate limits).

`run` judges each engine's results as returned — its own title and snippet —
with an LLM relevance judge (Google "Needs Met" 0–4) and scores RBP@5
(`p=0.8`, ceiling ≈ 0.672) with redundancy penalties for duplicate URLs and
repeated domains. Results identical across engines are judged once; the
`ultimate` engine takes the best rating per deduplicated URL.
`--snippet-chars` keeps judge evidence uniform across engines. `--queries`
also accepts plain text, one query per line.

## finance

Keyword queries about public companies (`"nvidia ceo"`, `"nvidia q1 fiscal
2026 net income"`) with gold answers from Wikidata, GLEIF, and SEC filings —
scored on whether top-K results *contain the answer*, not whether they hit
one pinned URL.

```bash
keenbench finance generate --max-companies 100 --per-company 1 --out gold.jsonl
keenbench finance run --queries gold.jsonl --judge --out report.json
```

Three suites (`--suites`): **`finance`** — registry facts per company
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

Known-item paper retrieval. Each paper yields four queries: **`title`**
(degraded title, answerable from metadata), **`body`** (a keyword query on a
full-text-only detail, machine-verified absent from title and abstract),
**`clue`** (the same kind of full-text facts phrased as a natural-language
question), and **`tot`** (a tip-of-the-tongue description: hedged,
half-remembered, with names and exact values banned and machine-verified
absent). The gaps between the buckets are the point: title vs body isolates
full-text indexing, body vs clue isolates keyword-vs-prose handling, and tot
isolates semantic retrieval. A paper is kept only if all requested buckets
pass, so buckets stay comparable; `--buckets` selects a subset.

```bash
keenbench scholar generate --age-buckets 7d,30d,1y --per-cell 10 --out gold.jsonl
keenbench scholar run --queries gold.jsonl --num-results 10 --out report.json
```

Gold comes from arXiv and Europe PMC, paired and balanced over
`(domain × age)` cells. Scoring is deterministic: result URLs and snippets
are scanned for arXiv ids, DOIs, and PMIDs; a query is a hit when an id
matches the gold paper. The report separates per-bucket recall
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

`keenbench.shared.agent` — a self-contained tool-calling agent: an `Agent`
loop with optional planning and context compaction, `mcp_tools_from_session`
to bridge MCP tools, `RunBudget` for hard dollar budgets.

Pipelines are pure (inputs + clients in, rows/reports out), so they also
drive from a notebook or scheduler: the ranking harness is
`keenbench.shared.rankeval.run_rbp`, the recall scorer
`keenbench.finance.score.run_answers`.

Every bench report carries a synthetic `ultimate` engine: the
pooled results of all engines per query, oracle-ranked — by judge rating
(redundancy-penalty aware) on the RBP benches, gold item first on the
known-item benches. It is the score ceiling any single engine could reach
and is excluded from the overlap and uniqueness stats.

## Continuous benchmarks

[`bench.yaml`](.github/workflows/bench.yaml) runs against all registered
engines: news hourly (`--limit 20`); daily with fresh gold —
finance 00:17 UTC (`--limit 120 --judge`), agentic_rare 06:17
(`--limit 100`), scholar 12:17 (`--per-cell 7`), legal 18:17. Each run
appends summary rows
(`history.jsonl`), engine-pair URL overlap (`overlap.jsonl`), and per-engine
unique-URL counts (`uniqueness.jsonl`) to `gh-pages`, rendered as a dashboard
at <https://super-journey-4z52474.pages.github.io/>, and archives full
artifacts to the HF dataset
[`keenable-ai/keenbench-results`](https://huggingface.co/datasets/keenable-ai/keenbench-results).
Each run also refreshes `daily_queries.jsonl` at the dataset root: a
rolling window of the queries evaluated by runs from the last 24 hours
(`scripts/daily_queries.py`; `backfill` rebuilds it from the archive).
Needs repo secrets `OPENROUTER_API_KEY`, `HF_TOKEN`, and the per-engine keys.

## Development

```bash
uv sync
uv run pytest   # deterministic, no network
```

## License

MIT — see [LICENSE](LICENSE).
