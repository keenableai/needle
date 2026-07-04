# keenbench

Hourly search-engine benchmarks. Two benches: freshstream (hourly, RBP@5, LLM
judge) and companyfill (daily, answer-recall@5 + MRR@5, deterministic matcher
with an LLM judge backstop on misses). rarestream is a query producer, not a
bench: it filters a query dataset down to English medium/long queries with rare
words, using the same BERT-wordpiece rarity definition as keenable-eval's
rare-entity producer. It defaults to the agentic search-log dataset
(`agentic/queries.parquet` on the HF dataset) and also handles the AQL
query-stream artifact (`aql/queries.jsonl`, produced by
github.com/keenableai/archive-query-log) via `--stream-path`/`--query-field`.
Reads/writes jsonl or parquet.

## Layout

- `dashboard/index.html` — the whole dashboard: one self-contained static page,
  vanilla JS, no build step. Deployed to gh-pages by the bench workflow.
- Dashboard data: `data/history.jsonl`, `data/latest_companyfill.json`, and
  `data/runs.json` are published next to the page; full per-run artifacts
  (`rbp.json`, `recall.json`) live on the HF dataset
  `keenable-ai/keenbench-results` and are fetched directly from there.
- Per-result report fields (`title`, `url`, `snippet`, `rating`, `penalized`,
  `label`, `reasoning`) are shaped in `src/keenbench/shared/rankeval.py` — keep
  the dashboard renderers in sync with it.

## Verifying dashboard changes (screenshot method)

There is no dev server or test data in the repo. To see a dashboard change
rendered:

1. Copy `dashboard/index.html` into a scratch dir as `site/index.html` and add
   fixture files under `site/data/`: `history.jsonl`, `runs.json`, and a run
   artifact (`rbp.json` or `recall.json`) matching the rankeval report shape.
2. Serve `site/` over local HTTP (any static server; `fetch` fails on file://).
3. Drive it with playwright-core, reusing what the machine already has before
   installing anything:
   - module: `find "$(npm root -g)" -path '*/playwright-core/index.mjs'` often
     finds a copy vendored by a global package — import it by absolute path
     (ESM ignores NODE_PATH). Otherwise `npm i playwright-core` in the scratch
     dir.
   - browser: pass `executablePath` pointing at a cached build under
     `~/.cache/ms-playwright/` or a system chromium; otherwise
     `npx playwright install chromium-headless-shell`.
4. Intercept the HF artifact fetch with
   `page.route('**/huggingface.co/**', ...)` and fulfill from the local
   fixture, open the page, click a `.qrow summary` to expand a query, and
   screenshot `#card-runs` (or whichever card changed).
5. Read the PNG to check the rendering; share it via paste.keenable.ai when a
   PR needs a screenshot.

## Rules

- No code comments or docstrings; rationale goes in commit/PR messages.
- Never commit to main; branch + PR, no force pushes or `--amend`.
- Python via UV only; sync with extras.
