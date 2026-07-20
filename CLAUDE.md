# keenbench

Hourly search-engine benchmarks; full docs in README.md. Four benches:
freshstream (hourly, RBP@5, LLM judge), companyfill (daily, answer-recall@5 +
MRR@5, deterministic matcher with LLM judge backstop), scholar (daily,
known-item papers, recall@10 + MRR@10 by arXiv/DOI/PMID match), and legal
(daily, known-item caselaw/CFR, recall@5 + MRR@5 by citation/docket/URL
match). rarestream is a query producer, not a bench: `scripts/rarestream_filter.py`
filters a query stream for English rare-word queries (BERT WordPiece +
fastText language ID), and `keenbench rarestream generate` / `run` samples
the filtered artifact and evaluates it like freshstream.

## Layout

- `dashboard/index.html` — the whole dashboard: one self-contained static
  page, vanilla JS, no build step; deployed to gh-pages by the bench workflow.
- Dashboard data: `data/history.jsonl`, `overlap.jsonl`, `uniqueness.jsonl`,
  `latest_*.json`, and `runs.json`, published by `scripts/publish_bench.py`;
  full per-run artifacts (`rbp.json`, `recall.json`) live on the HF dataset
  `keenable-ai/keenbench-results` and are fetched directly from there.
- Per-result report fields (`title`, `url`, `snippet`, `rating`, `penalized`,
  `label`, `reasoning`) are shaped in `src/keenbench/shared/rankeval.py` —
  keep the dashboard renderers in sync with it.

## Verifying dashboard changes

No dev server or test data in the repo. Copy `dashboard/index.html` into a
scratch `site/`, add fixtures under `site/data/` (`history.jsonl`,
`runs.json`, an `rbp.json`/`recall.json` in the rankeval shape), and serve
over local HTTP (`fetch` fails on file://). Screenshot with playwright-core:
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
