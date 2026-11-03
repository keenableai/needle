> For the complete documentation index, see [llms.txt](../llms.txt).

# Did the answer reach the agent? Finance retrieval.

answer-recall@5 + MRR@5 · daily · deterministic + LLM backstop.

Finance queries have known answers from Wikidata, GLEIF, and SEC filings. NEEDLE does not ask whether an engine linked a preferred URL. It asks whether the gold fact appeared in the top-5 titles and snippets an agent will read.

- [Compare providers on finance](../compare.md)
- [Methodology](../methodology.md)
- [latest_finance.json](../data/latest_finance.json)

## Queries

Registry facts (CEO, founded year, HQ, employees, LEI, ticker) and single-quarter 10-Q numbers, plus known-item filing retrieval by accession number.

## Score

Deterministic matchers (nickname-tolerant names, 2% money band, domain match). An LLM backstop may upgrade a miss; it never revokes a hit.

## Why it exists

Product demos can look fluent while the snippet never contains the number. This bench measures evidence, not prose.

The 7-day leaderboard on the HTML page is marked `data-markdown-ignore`. Those numbers are computed in the browser from [history.jsonl](../data/history.jsonl). They are not sample copy. Do not invent live scores. The live dashboard, including per-query judgements, is on the [home leaderboards](../index.md).

NEEDLE is an MIT-licensed benchmark from [Keenable](https://keenable.ai). Cite [DOI 10.5281/zenodo.22095155](https://doi.org/10.5281/zenodo.22095155).
