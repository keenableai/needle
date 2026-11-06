# NEEDLE

Hourly search-engine benchmarks; full docs in README.md. Four benches:
news (hourly, nDCG@5, LLM judge), finance (daily, answer-recall@5 +
MRR@5, deterministic matcher with LLM judge backstop), scholar (daily,
known-item papers, recall@10 + MRR@10 by arXiv/DOI/PMID match), and legal
(daily, known-item caselaw/CFR, recall@5 + MRR@5 by citation/docket/URL
match). agentic_rare is a query producer, not a bench: `scripts/agentic_rare_filter.py`
filters a query stream for English rare-word queries (BERT WordPiece +
fastText language ID), and `needle agentic_rare generate` / `run` samples
the filtered artifact and evaluates it like news.

## Layout

- `dashboard/` — static site, vanilla JS, no build step; the bench workflow
  deploys the tree to gh-pages. `index.html` is the live leaderboard;
  `compare/`, `news/`, `finance/`, `scholar/`, `legal/`, and `methodology/`
  are crawlable subpages; `assets/` holds shared CSS/JS; `llms.txt`,
  `llms-full.txt`, `robots.txt`, and `sitemap.xml` are for search/GEO.
- Dashboard data: `scripts/publish_bench.py` publishes `data/history.jsonl`,
  `overlap.jsonl`, `uniqueness.jsonl`, `independence.json` (their
  all-runs and last-7-days totals, the only form the dashboard loads),
  `latest_*.json`, `runs.json`, `families.json`, and `catalog.json`;
  `history.jsonl` keeps raw `lat_ms` samples only for the last 7 days;
  per-run artifacts live on the HF dataset
  `keenable-ai/needle-results` as a slim `<bench>.json` whose engine
  entries carry `per_query_path` pointing at `<bench>/<engine>.json`; the
  dashboard follows the pointer, and `needle.shared.hf.fetch_report` merges
  the files back for scripts. Runs before 2026-09-16 hold one full file.
- `src/needle/shared/rankeval.py` shapes the per-result report fields
  (`title`, `url`, `snippet`, `rating`, `penalized`, `label`, `reasoning`,
  `gates`) — keep the dashboard renderers in sync with it.

## Verifying dashboard changes

No dev server or test data in the repo. Copy the `dashboard/` tree into a
scratch `site/`, add fixtures under `site/data/` (`history.jsonl`,
`runs.json`, `catalog.json`, an `ndcg.json`/`recall.json` in the rankeval
shape), and serve over local HTTP (`fetch` fails on file://). Screenshot
with playwright-core:
reuse the globally vendored module (`find "$(npm root -g)" -path
'*/playwright-core/index.mjs'`, import by absolute path) and a cached
chromium under `~/.cache/ms-playwright/`. Intercept
`page.route('**/huggingface.co/**', ...)` to fulfill the artifact fetch from
the fixture, click a `.qrow summary` to expand a query, screenshot the
changed card, and Read the PNG. Share via paste.keenable.ai when a PR needs
it.

## Rules

- No code comments or docstrings; rationale goes in commit/PR messages.
- Never commit to main; branch + PR, no force pushes or `--amend`.
- Python via UV only; sync with extras.
