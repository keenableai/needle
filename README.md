# NEEDLE

[![CI](https://github.com/keenableai/needle/actions/workflows/ci.yaml/badge.svg)](https://github.com/keenableai/needle/actions/workflows/ci.yaml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22095155.svg)](https://doi.org/10.5281/zenodo.22095155)

Search and retrieval benchmarks from [Keenable.ai](https://keenable.ai). A
benchmark is a query set plus a scoring method. Each one is a module under
`needle` with the same two subcommands:

```bash
needle <benchmark> generate ... --out queries.jsonl   # produce query rows (JSONL)
needle <benchmark> run --queries queries.jsonl ...    # evaluate engines on them (JSON report)
```

| Benchmark | Queries | Scoring |
| --- | --- | --- |
| [`news`](#news) | fresh, time-sensitive queries from live RSS + Google Trends | LLM relevance judge → nDCG@5 |
| [`finance`](#finance) | company and financial fact lookups, gold from public registries and SEC filings | answer-recall@K + MRR@K, deterministic (optional LLM backstop) |
| [`scholar`](#scholar) | known-item paper retrieval: by title vs. by a full-text-only detail | recall@K + MRR@K by paper-id match |
| [`legal`](#legal) | known-item caselaw / CFR retrieval | recall@K + MRR@K by citation/docket/URL identity |
| [`agentic_rare`](#agentic_rare) | English rare-word queries sampled from a filtered query stream | LLM relevance judge → nDCG@5 |

Each bench generates gold on demand from public sources; the repo commits
none of it. `agentic_rare` differs: it is a query producer plus a news-style
eval, with no gold of its own.

## Install

Uses [uv](https://docs.astral.sh/uv/): `uv sync`, then `uv run needle ...`
(or `uv tool install --editable .` for a global `needle`).

## Configuration

The CLI loads `.env` from the working directory (copy
[`.env.example`](.env.example)); exported variables take precedence.

| Variable | Purpose |
| --- | --- |
| `OPENROUTER_API_KEY` | all LLM work — query projection (news, finance `filingdoc`, scholar, legal `code`) and judging |
| `EXA_API_KEY`, `SERPER_API_KEY` (`google`), `SEARCHAPI_API_KEY` (`bing`), `BRAVE_API_KEY`, `PARALLEL_API_KEY`, `TAVILY_API_KEY`, `PERPLEXITY_API_KEY`, `OCTEN_API_KEY`, `CERAMIC_API_KEY`, `YOU_API_KEY` | one per engine, required when that engine is in `--engines` |
| `KEENABLE_API_KEY` | optional — without it the CLI uses the keyless, rate-limited endpoint |
| `NEEDLE_LLM_MODEL`, `NEEDLE_JUDGE_MODEL` | both default to `openai/gpt-5.6-terra`; `--llm-model` / `--judge-model` override |

All `run` commands share one interface:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--queries` | (required) | JSONL query rows, typically from `generate` |
| `--out` | `-` | report path; `-` = stdout |
| `--engines` | `keenable,exa` | comma-separated engine list |
| `--num-results` | `5` | top-K fetched and scored per engine |
| `--snippet-chars` | `2000` | uniform cap on per-result evidence text (`0` = no cap), so engines that return more text get no free evidence; also sent as the snippet-length request budget to engines that accept one (keenable, exa, ceramic), clamped to each API's range |
| `--limit` / `--sample` / `--seed` | `0` / `stratified` / `0` | deterministic sample of N queries |
| `--judge-model` / `--judge-concurrency` | env / `8` | LLM judge knobs |

Every engine issues one request at a time, so latency samples are comparable
across engines. Per-engine tuning uses env vars: `TAVILY_DEPTH`; the engine
entry fixes Keenable's, Exa's, and Parallel's modes (`keenable` = pro,
`keenable-realtime` = realtime, `exa` = auto, `exa-instant` = instant,
`parallel` = advanced, `parallel-turbo` = turbo). The mean skips queries whose
search or judging failed
(via `num_scored`; the report lists `search_errors` / `judge_errors`) and
does not score them as zero.

## news

Turns what trends right now into keyword queries; the bench scores how well
each engine ranks results for them.

```bash
needle news generate --source rss --out queries.jsonl    # or --source trending
needle news run --queries queries.jsonl --limit 20 --out ndcg.json
```

`generate` builds one cohort from two sources. **RSS**: ~124 curated public
feeds, the newest item per feed within a freshness window (1h for most feeds,
168h for papers); when too few survive, the least-stale items fill the gap.
**Google Trends**: the keyless Trends RSS across all 52 US geos, merged,
fuzzy-deduped, capped by traffic. An LLM projects each item into a query and
refuses evergreen content. `query_id` is deterministic from
`(query_text, hour_ts)`. The feed list lives in
[`feeds.default.toml`](src/needle/news/configs/feeds.default.toml)
(override with `--feeds`; honor each publisher's ToS and rate limits).

`run` judges each engine's results as returned — its own title and snippet —
with an LLM relevance judge (Google "Needs Met" 0–4) and scores nDCG@5 with
a redundancy penalty for duplicate URLs. The ideal ranking is the pooled
`ultimate` ordering — the best rating per deduplicated URL across all
engines, oracle-ranked — so `ultimate` scores exactly 1 and queries where
no engine found anything relevant are excluded.
The judge rates results identical across engines once.
`--snippet-chars` keeps judge evidence uniform across engines. `--queries`
also accepts plain text, one query per line.

## finance

Keyword queries about public companies (`"nvidia ceo"`, `"nvidia q1 fiscal
2026 net income"`) with gold answers from Wikidata, GLEIF, and SEC filings.
The score asks whether top-K results *contain the answer*, not whether they
hit one pinned URL.

```bash
needle finance generate --max-companies 100 --per-company 1 --filingdoc-target 40 --out gold.jsonl
needle finance run --queries gold.jsonl --judge --out report.json
```

Three suites (`--suites`): **`finance`** — registry facts per company
(ceo, ceo_since, ceo_company, founded_year, hq_country, website, employees,
lei, ticker), each asked as a keyword query and, where a template exists, as
a natural-language variant (bucket `finance_nl`); **`filings`** —
single-quarter 10-Q facts (default net income, operating income,
diluted EPS; `--fields` can add revenue) from SEC XBRL, stratified by
market cap; **`filingdoc`** —
known-item filing retrieval, gold = the accession number. ~50% of
`filings`/`filingdoc` queries carry operator syntax (`"quoted"`, `site:`,
`after:`/`before:`), tagged in `query_origin.syntax`.

A deterministic matcher scores each field: nickname-tolerant person names,
a 2% band for money, 15% for employee counts, country aliases,
registrable-domain match for websites, and required cue words for
low-entropy fields so a stray number cannot score. `--judge` adds an LLM
backstop, consulted only for rejected results ranked ahead of the first
deterministic hit — it can upgrade a miss but never revoke a hit. The report
breaks down by field, suite, syntax, cap tier, and freshness, and splits
misses into system-specific vs universal. Snippet-only checks give a lower
bound, the same for every engine.

## scholar

Known-item paper retrieval. Each paper yields four queries: **`title`**
(degraded title, answerable from metadata), **`body`** (a keyword query on a
full-text-only detail, machine-verified absent from title and abstract),
**`clue`** (the same kind of full-text facts phrased as a natural-language
question), and **`tot`** (a tip-of-the-tongue description: hedged,
half-remembered, with names and exact values banned and machine-verified
absent). The gaps between buckets are the goal: title vs body isolates
full-text indexing, body vs clue isolates keyword-vs-prose handling, and tot
isolates semantic retrieval. A paper stays only if all requested buckets
pass, so buckets remain comparable; `--buckets` selects a subset.

```bash
needle scholar generate --age-buckets 7d,30d,1y --per-cell 10 --out gold.jsonl
needle scholar run --queries gold.jsonl --num-results 10 --out report.json
```

Gold comes from two suites (`--suites`): `arxiv` and `europepmc`, paired
and balanced over `(domain × age)` cells. Scoring is deterministic: the scorer scans result
URLs and snippets for arXiv ids, DOIs, and PMIDs; a query is a hit when an
id matches the gold paper. The report separates per-bucket recall
(`by_bucket`) and splits misses into system-specific vs universal. Pages
with no inline identifier cannot match, so recall is a lower bound, the
same for every engine.

## legal

Known-item legal retrieval; gold is a document identity from the citation
graph, so it needs no expert annotation. ~50% of queries carry operator
syntax.

```bash
needle legal generate --per-court 4 --per-title 4 --out legal.jsonl
needle legal run --queries legal.jsonl --out legal.json
```

Two suites (`--suites`): **`caselaw`** — recent published opinions from the
CourtListener API across 14 federal courts, one caption-style query per case
(gold: reporter citations, docket + party tokens, cluster id); **`code`** —
eCFR sections; an LLM projects each into a query about the section's
substance with one verbatim quoted span, and the bench rejects it if it
leaks the citation (gold: the `title CFR section` citation). `run` scans
result URLs and snippets for reporter citations, docket numbers (scored only
next to a gold party token), CourtListener/Justia URLs, and CFR citations;
it breaks down by suite, syntax, and court.

## agentic_rare

A query producer plus a news-style eval for English rare-word queries.

```bash
uv run python scripts/agentic_rare_filter.py --out rare_entity.parquet   # refresh the filtered artifact
needle agentic_rare generate --limit 100 --out queries.jsonl
needle agentic_rare run --limit 100 --out report.json
```

`scripts/agentic_rare_filter.py` reads a query stream
(`agentic/queries.parquet` on the HF dataset) and keeps queries with at
least one rare word: a word that BERT WordPiece splits into ≥5 subwords or
maps to `[UNK]`. It drops too-short, too-long, URL-like, and non-Latin
queries, plus VINs, hex hashes, and crypto addresses. fastText language ID
gates language: it rejects confident non-English, accepts confident
English, and otherwise requires that most non-rare words are common English
(wordfreq). An n-gram cap (3-grams, max 2 each) dedups near-copies. Each
kept row carries `length_bucket` (short/medium/long by word count) and its
hard words with their subword splits.

`generate` and `run` sample the filtered artifact
(`agentic/rare_entity.parquet`), stratified by `length_bucket`; `run`
scores exactly like news (LLM relevance judge, nDCG@5). `--queries` reads a
local file instead of the HF artifact; `run --queries-out` also saves the
sampled query rows.

## Shared infrastructure

`needle.shared.search` — a `SearchClient` protocol (errors-as-data
`async search(query, *, num_results) -> (results, error)`) with clients for
every engine above. The client parses out Google-style operators (`site:`,
`after:`, `before:`) and translates each to the engine's best native
mechanism; it drops unsupported ones rather than send them as literal
tokens. To add an engine: subclass `HttpSearchClient`, map its response to
`SearchResult`, add an `EngineSpec` to `ENGINES` in
[`factory.py`](src/needle/shared/search/factory.py), and set the key env
var — reports and the dashboard pick it up automatically.

Pipelines are pure (inputs + clients in, rows/reports out), so a notebook or
scheduler can also drive them: the ranking harness is
`needle.shared.rankeval.run_ndcg`, the recall scorer
`needle.finance.score.run_answers`.

Every bench report carries a synthetic `ultimate` engine: the pooled results
of all engines per query, oracle-ranked — by judge rating on the judged
benches, gold item first on the known-item benches. It is the nDCG ideal
ranking on the judged benches and the score ceiling for any single engine;
the overlap and uniqueness stats exclude it.

## Continuous benchmarks

[`bench.yaml`](.github/workflows/bench.yaml) runs against all registered
engines: news hourly (`--limit 20`); daily with fresh gold — finance 00:17
UTC (`--limit 120 --judge`), agentic_rare 06:17 (`--limit 100`), scholar
12:17 (`--per-cell 7`), legal 18:17. Gold lives on `gh-pages` between runs;
a daily bench also runs off-schedule when a manual dispatch selects it or
when its gold file is missing. Each run appends summary rows
(`history.jsonl`), engine-pair URL overlap (`overlap.jsonl`), and per-engine
unique-URL counts (`uniqueness.jsonl`) to `gh-pages`; the dashboard at
<https://keenableai.github.io/needle/> renders them. Each run also
archives full artifacts to the HF dataset
[`keenable-ai/needle-results`](https://huggingface.co/datasets/keenable-ai/needle-results)
and refreshes `daily_queries.jsonl` at the dataset root: a rolling window of
the queries evaluated by runs from the last 24 hours
(`scripts/daily_queries.py`; `backfill` rebuilds it from the archive). The
workflow needs repo secrets `OPENROUTER_API_KEY`, `HF_TOKEN`, and the
per-engine keys.

## Development

```bash
uv sync
uv run pytest   # deterministic, no network
```

## Citation

```bibtex
@misc{needle2026,
  author = {Styskin, Andrey and Petri, Matthias and Gusev, Ilya},
  title  = {NEEDLE: A Live Open-Source Search Benchmark for AI Agents},
  year   = {2026},
  url    = {https://keenableai.github.io/needle/},
  note   = {Contact: andrey@keenable.ai, matthias@keenable.ai, ilya.gusev@keenable.ai}
}
```

## License

MIT — see [LICENSE](LICENSE).
