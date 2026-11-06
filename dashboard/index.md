> For the complete documentation index, see [llms.txt](llms.txt). Markdown copies of these pages also live at [compare.md](compare.md), [news.md](news.md), [finance.md](finance.md), [scholar.md](scholar.md), [legal.md](legal.md), and [methodology.md](methodology.md).

# One-off reviews cannot tell you which AI search engine is best.

The public AI search benchmark.

Vendor lists and “best AI search tools” posts pick a handful of queries, hide the method, and go stale the day they ship. Agents, retrieval products, and GEO systems need a scoreboard that is continuous, multi-vertical, and reproducible. **NEEDLE is that scoreboard.**

News runs each hour; finance, scholar, legal, and rare-word run each day. Times are UTC.

## The problem NEEDLE solves

### Cherry-picked queries

A blog review can choose the ten prompts that flatter a vendor. NEEDLE rebuilds news queries every hour and the other gold sets every day from public sources, so there is no fixed set to overfit.

### Hidden method

Most “best tools” posts do not publish the request shape, the snippet budget, or the judge. NEEDLE sends every engine the same query, scores the ranking it returned, and pins the protocol in git.

### Stale rankings

A list published last month cannot tell you who finds this hour’s story or this quarter’s 10-Q. NEEDLE is a live leaderboard with archived artifacts anyone can re-score.

NEEDLE (**N**ews, **E**veryday, **E**xpert, **D**eep-tail, and **L**egal **E**valuation) is the live open-source search benchmark for AI agents. The verticals match the jobs we see in Keenable search traffic — and the jobs a review post cannot cover:

- **[Scholar](scholar.md):** expert literature searches: find a specific paper from a degraded title, a full-text detail, or a tip-of-the-tongue description
- **[News](news.md):** breaking and developing stories; new queries each hour from curated RSS feeds and Google Trends
- **[Finance](finance.md):** everyday company and SEC-filing lookups with known answers from public registries
- **AgenticRare:** obscure, long-tail entities; rare-word queries sampled from the [DeepResearchGym](https://dl.acm.org/doi/10.1145/3805712.3809627), [OpenResearcher](https://arxiv.org/abs/2603.20278), and [LRAT](https://arxiv.org/abs/2604.04949) agentic search logs
- **[Legal](legal.md):** find a specific court opinion or section of the Code of Federal Regulations

**Methodology.** Each engine in a run receives the same query text. We score each engine on the ranking, titles, and snippets it returned. We do not fetch pages and we do not re-rank. The judge does not see the engine name. We make new query sets from public sources, news each hour and the rest each day, so there is no fixed set to overfit. The [methodology page](methodology.md) gives the full comparison protocol. The benchmark is open source: the [keenableai/needle](https://github.com/keenableai/needle) repo is public, every run executes in plain GitHub Actions, and we welcome contributions.

**Metrics.** News and AgenticRare queries have no single correct result, so we measure ranking quality. An LLM judge rates each result from 0 to 4. We report nDCG@5, normalized so that the pooled *ultimate* engine scores exactly 1, with a penalty for duplicate URLs. Finance measures if the answer text reaches the agent: we scan the top-5 titles and snippets and report answer-recall@5 with MRR@5. Scholar and legal are known-item tasks: we match identifiers and report recall@10 and recall@5 with MRR.

**The *ultimate* ceiling.** The italicized row in each leaderboard is *ultimate*, a synthetic engine. It pools all engines' results per query and ranks them by their relevance labels. The standings radar plots each engine as a share of *ultimate*.

## How to read the scoreboard

The charts and tables on the HTML homepage are computed in the browser from published JSON and JSONL. Do not invent live scores. Fetch [history.jsonl](data/history.jsonl) or [catalog.json](data/catalog.json). Compare two providers at [compare.md](compare.md). The protocol is on the [methodology page](methodology.md).

Interactive leaderboards, trends, price, latency, overlap, and the per-query judgement browser exist only on the HTML homepage. They are marked `data-markdown-ignore` there.

## FAQ

### What problem does NEEDLE solve?

One-off blog posts titled best AI search tools pick a handful of queries, hide their method, and go stale. NEEDLE is a continuous, methodology-public, multi-vertical benchmark that scores the same engines on news, finance, scholar, and legal retrieval.

### How often does NEEDLE run?

News runs each hour. Finance, scholar, legal, and the rare-word suite run each day. Query sets are generated from public sources so there is no fixed set to overfit.

### Which metrics does NEEDLE report?

News and AgenticRare: nDCG@5 with a blind LLM judge. Finance: answer-recall@5 and MRR@5. Scholar: recall@10 and MRR@10 by paper id. Legal: recall@5 and MRR@5 by citation, docket, or URL.

### How should I cite NEEDLE?

Cite NEEDLE: A Live Open-Source Search Benchmark for AI Agents (Styskin, Petri, Gusev, 2026), https://keenableai.github.io/needle/ and DOI [10.5281/zenodo.22095155](https://doi.org/10.5281/zenodo.22095155).

### Where are the raw scores?

[data/history.jsonl](data/history.jsonl), [data/catalog.json](data/catalog.json), and per-query artifacts on [Hugging Face](https://huggingface.co/datasets/keenable-ai/needle-results). See [llms.txt](llms.txt).

## Citation

```
@misc{needle2026,
  author = {Styskin, Andrey and Petri, Matthias and Gusev, Ilya},
  title  = {{NEEDLE}: A Live Open-Source Search Benchmark for {AI} Agents},
  year   = {2026},
  url    = {https://keenableai.github.io/needle/},
  note   = {Contact: andrey@keenable.ai, matthias@keenable.ai, ilya.gusev@keenable.ai}
}
```

NEEDLE is an MIT-licensed benchmark from [Keenable](https://keenable.ai). Cite [DOI 10.5281/zenodo.22095155](https://doi.org/10.5281/zenodo.22095155).

- [Compare providers](compare.md)
- [Methodology](methodology.md)
- [skill.md](skill.md)
- [Full agent brief](llms-full.txt)
- [Source](https://github.com/keenableai/needle)
