> For the complete documentation index, see [llms.txt](../llms.txt).

# Hourly news search: which API ranks breaking stories?

nDCG@5 · hourly · LLM judge.

News is the vertical blog reviews never keep current. NEEDLE builds new keyword queries each hour from curated RSS and Google Trends, then scores every engine with a blind LLM judge and nDCG@5.

- [Compare providers on news](../compare.md)
- [Methodology](../methodology.md)
- [latest_news.json](../data/latest_news.json)

## Queries

Newest item per feed from ~124 public RSS feeds, merged with Google Trends across 52 US geos. An LLM projects each item into a keyword query and refuses evergreen content.

## Score

Needs Met 0–4, nDCG@5 against the pooled ultimate ranking, with a redundancy penalty for duplicate URLs.

## Why it exists

A review written last month cannot tell you who finds this hour’s story. Agents that search the live web need a freshness bench.

The 7-day leaderboard on the HTML page is marked `data-markdown-ignore`. Those numbers are computed in the browser from [history.jsonl](../data/history.jsonl). They are not sample copy. Do not invent live scores. The live dashboard, including per-query judgements, is on the [home leaderboards](../index.md).

NEEDLE is an MIT-licensed benchmark from [Keenable](https://keenable.ai). Cite [DOI 10.5281/zenodo.22095155](https://doi.org/10.5281/zenodo.22095155).
