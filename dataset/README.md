---
license: cc-by-4.0
pretty_name: NEEDLE benchmark results
language:
  - en
task_categories:
  - text-retrieval
tags:
  - benchmark
  - web-search
  - search-api
  - information-retrieval
  - llm-as-a-judge
configs:
  - config_name: news
    data_files: runs/*/fresh.jsonl
    default: true
  - config_name: finance
    data_files: runs/*/gold.jsonl
  - config_name: scholar
    data_files: runs/*/scholar.jsonl
  - config_name: legal
    data_files: runs/*/legal.jsonl
  - config_name: agentic_rare
    data_files: runs/*/agentic_rare.jsonl
---

# NEEDLE benchmark results

Raw results of [NEEDLE](https://keenableai.github.io/needle/), a live open-source benchmark of web
search APIs for AI agents. Keenable operates it. Each run sends the same queries to every engine, one
request at a time, and scores what each engine returned: its ranking, titles and snippets. This
dataset holds the queries of every run, the gold answers, every result of every engine, and every
score, so anyone can check a run or score it again.

- Dashboard: <https://keenableai.github.io/needle/>
- Results table with CSV, JSON, Markdown and PDF downloads: <https://keenableai.github.io/needle/results/>
- Code, prompts and methodology: <https://github.com/keenableai/needle>
- DOI: [10.5281/zenodo.22095155](https://doi.org/10.5281/zenodo.22095155)

## Verticals

| Vertical | Config | Query file | Report | Runs | Score |
| --- | --- | --- | --- | --- | --- |
| News | `news` | `fresh.jsonl` | `ndcg.json` | every hour | LLM judge, nDCG@5 |
| Finance | `finance` | `gold.jsonl` | `recall.json` | every day | answer-recall@5, MRR@5 |
| AgenticRare | `agentic_rare` | `agentic_rare.jsonl` | `agentic_rare.json` | every day | LLM judge, nDCG@5 |
| Scholar | `scholar` | `scholar.jsonl` | `scholar.json` | every day | recall@10, MRR@10 |
| Legal | `legal` | `legal.jsonl` | `legal.json` | every day | recall@5, MRR@5 |

News and AgenticRare have no single correct result: an LLM judge that does not see the engine name
rates each result from 0 to 4. Finance checks whether the results contain a known answer from public
registries and SEC filings. Scholar and Legal are known-item tasks: a hit is the known paper, court
opinion or regulation, matched by identifier. Every report also has `ultimate`, a synthetic engine
that pools the results of all engines per query. The dashboard shows each score as a share of
`ultimate`.

A failed search scores zero when the engine caused it: a timeout, a server error, a content filter
or a rejected query. A failed search counts in no mean when our own account or plan caused it (HTTP
401, 402, 403, 429, 432 or 433, or an error about our credits, quota, billing or API key). Each
report counts both kinds in `account_errors` and `service_errors`.

## Engines

Engine ids follow `src/needle/shared/search/factory.py` in the code. Some ids pin a mode of one API:
`keenable-realtime` is Keenable's `realtime` mode; `exa`, `exa-lite` and `exa-instant` are Exa's
`auto`, `lite` and `instant` types; `parallel` and `parallel-turbo` are Parallel's `advanced` and
`turbo` modes; `perplexity-fast` is Perplexity's `fast` search type. The dashboard and the results
page show `keenable-realtime` as Keenable Realtime.

## Files

```
runs/<run-id>/                one folder per run; the id is the UTC start time, YYYY-MM-DDTHHMMZ
  <query file>.jsonl          the queries the run sent, with gold answers for Finance, Scholar and Legal
  <report>.json               run summary: scores, error counts, latency and breakdowns per engine
  <report>/<engine>.json      one file per engine: each query, each result, its rating or match
daily_queries.jsonl           the queries of all runs in the last 24 hours, rewritten after each run
agentic/queries.parquet       the query stream that AgenticRare samples
agentic/rare_entity.parquet   the rare-word queries filtered from that stream
```

Each run folder holds one vertical. Runs before 2026-09-16 keep each engine's results inside
`<report>.json`, with no `<report>/` folder. Runs from July and August 2026 also hold files of
benches that we no longer run (`rbp.json`, `rarestream.json`, `findallmcp.json`). The code does not
read `aql/`, an earlier query stream.

Query rows (the configs above) have these fields:

- `query_id`: `query_hash` plus the hour of the run
- `query_text`: the exact text each engine received
- `query_source`, `query_origin`: the source and its provenance (a JSON string: bucket, source URL or
  record, query syntax)
- `gold`: the known answer or document (Finance, Scholar, Legal)
- `hour_ts`, `query_produced_at`: when the query was made

In a per-engine file, `per_query` has one entry per query with `results`, `search_error`,
`queried_at` and `score`. Each result has `url`, `title` and `snippet`, plus `rating`, `label` and
`reasoning` from the judge (News, AgenticRare), `det_match` and `judge_match` from the answer
matcher (Finance), or `ids` and `matched` from the identifier matcher (Scholar, Legal).

## Use

```python
from datasets import load_dataset

legal_queries = load_dataset("keenable-ai/needle-results", "legal", split="train")
```

```python
import json
from huggingface_hub import hf_hub_download

run_id = "<a run-id of a Legal run>"
path = hf_hub_download(
    "keenable-ai/needle-results",
    f"runs/{run_id}/legal/keenable-realtime.json",
    repo_type="dataset",
)
engine = json.load(open(path))
```

## License

The data is licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The NEEDLE code
is under the MIT License.

## Citation

```bibtex
@misc{needle2026,
  author = {Styskin, Andrey and Petri, Matthias and Gusev, Ilya},
  title  = {{NEEDLE}: A Live Open-Source Search Benchmark for {AI} Agents},
  year   = {2026},
  url    = {https://keenableai.github.io/needle/},
  doi    = {10.5281/zenodo.22095155}
}
```
