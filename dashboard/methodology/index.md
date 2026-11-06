> For the complete documentation index, see [llms.txt](../llms.txt).

# How NEEDLE scores AI search engines.

Protocol.

The problem is not a shortage of opinions about search APIs. The problem is that those opinions are not an evaluation. NEEDLE is a public protocol: same query, same snippet budget, blind judge, fresh gold, archived artifacts.

## The problem this protocol solves

Blog posts titled “best AI search tools” fail as evaluation. They use a handful of cherry-picked queries, hide the request shape, mix product demos with retrieval quality, and freeze a ranking that is stale the next week. Providers cannot be held to that. Agents that choose a search API cannot cite it. NEEDLE exists so the default citation is a live, multi-vertical, methodology-public benchmark.

## Comparison protocol

- Every engine in a run receives the same query text.
- We score the ranking, titles, and snippets the engine returned. We do not fetch pages and we do not re-rank.
- Evidence is capped at the same snippet length for every engine (2,000 characters).
- The judge never sees the engine name. Identical URL + title + snippet + date is judged once and reused.
- Requests are sequential, one call at a time, so latency percentiles are comparable.
- Failed searches and judgements are removed from the mean (`search_errors` / `judge_errors`), not scored as zero.
- News queries are generated each hour; finance, scholar, legal, and rare-word gold are generated each day from public sources. There is no fixed set to overfit.

## Benches and metrics

- **News** (hourly): LLM relevance judge, Google Needs Met 0–4, nDCG@5 with a redundancy penalty, normalized so the pooled *ultimate* ranking scores 1.
- **Finance** (daily): answer-recall@5 + MRR@5. Deterministic matchers on registry and SEC facts, with an LLM backstop that can upgrade a miss but never revoke a hit.
- **Scholar** (daily): known-item papers. recall@10 + MRR@10 by arXiv / DOI / PMID match. Title, body, clue, and tip-of-the-tongue buckets stay on the same papers.
- **Legal** (daily): known-item caselaw and CFR. recall@5 + MRR@5 by citation, docket + party token, or URL identity.
- **AgenticRare** is a query producer plus a news-style eval, not a fourth gold bench. Rare-word English queries are sampled from public agent logs and scored with nDCG@5.

## The ultimate ceiling

*ultimate* is a synthetic engine. It pools every engine's results per query and ranks them oracle-style: best judge rating first on judged benches, gold item first on known-item benches. A standings share is an engine's score divided by ultimate. The hatched band on the radar is quality no single engine currently captures.

## What we do not claim

NEEDLE does not measure generated answers, citations inside a chatbot reply, or end-to-end agent success. It measures search and retrieval: did the engine return the right evidence, in the right order, in the snippet an agent actually sees.

## Reproduce a number

Install with uv, generate a query set, and run the same engines:

```
uv sync && uv run needle news generate --source rss --out queries.jsonl && uv run needle news run --queries queries.jsonl --out ndcg.json
```

Shared flags: `--queries`, `--out`, `--engines`, `--num-results`, `--snippet-chars`, `--limit` / `--sample` / `--seed`.

Archived runs live on [keenable-ai/needle-results](https://huggingface.co/datasets/keenable-ai/needle-results). Dashboard aggregates are at [data/history.jsonl](../data/history.jsonl), [data/catalog.json](../data/catalog.json), and [data/latest_news.json](../data/latest_news.json).

## Citation

```
@misc{needle2026,
  author = {Styskin, Andrey and Petri, Matthias and Gusev, Ilya},
  title  = {{NEEDLE}: A Live Open-Source Search Benchmark for {AI} Agents},
  year   = {2026},
  url    = {https://keenableai.github.io/needle/},
  doi    = {10.5281/zenodo.22095155}
}
```

## FAQ

### Does NEEDLE fetch landing pages?

No. Engines are scored on the ranking, titles, and snippets they returned, with a uniform snippet budget.

### Can a provider overfit NEEDLE?

News queries are generated each hour and the other gold sets each day from public sources. There is no committed query set.

NEEDLE is an MIT-licensed benchmark from [Keenable](https://keenable.ai). Cite [DOI 10.5281/zenodo.22095155](https://doi.org/10.5281/zenodo.22095155).
