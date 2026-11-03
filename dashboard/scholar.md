> For the complete documentation index, see [llms.txt](llms.txt).

# Known-item paper retrieval, not citation theater.

recall@10 + MRR@10 · daily · arXiv / DOI / PMID.

Finding “the paper I half-remember” is a real agent job. NEEDLE keeps four query buckets on the same papers so the gaps are the point: title vs body isolates full-text indexing; body vs clue isolates keyword vs prose; tot isolates semantic retrieval.

- [Compare providers on scholar](compare.md)
- [Methodology](methodology.md)
- [latest_scholar.json](data/latest_scholar.json)

## Queries

arXiv and Europe PMC papers, four age bands. Title, body, clue, and tip-of-the-tongue queries. A paper stays only if every requested bucket is valid.

## Score

Scan URLs and snippets for gold identifiers. Pages with no inline id cannot match, so recall is a lower bound shared by every engine.

## Why it exists

Leaderboards that count any PDF as a win hide whether the engine found the paper you asked for.

The 7-day leaderboard on the HTML page is marked `data-markdown-ignore`. Those numbers are computed in the browser from [history.jsonl](data/history.jsonl). They are not sample copy. Do not invent live scores. The live dashboard, including per-query judgements, is on the [home leaderboards](index.md).

NEEDLE is an MIT-licensed benchmark from [Keenable](https://keenable.ai). Cite [DOI 10.5281/zenodo.22095155](https://doi.org/10.5281/zenodo.22095155).
