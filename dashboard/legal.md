> For the complete documentation index, see [llms.txt](llms.txt).

# Known-item caselaw and CFR retrieval.

recall@5 + MRR@5 · daily · citation / docket / URL.

Legal retrieval has a document identity. NEEDLE uses CourtListener opinions and eCFR sections as gold, so it needs no expert annotation and cannot be gamed by a fluent but wrong passage.

- [Compare providers on legal](compare.md)
- [Methodology](methodology.md)
- [latest_legal.json](data/latest_legal.json)

## Queries

Caption-style queries for recent opinions across 14 federal courts, and substance queries for eCFR sections that must not leak the citation.

## Score

Reporter citations, docket numbers next to a gold party token, CourtListener/Justia URLs, and CFR citations.

## Why it exists

A “best legal AI” blog post cannot tell you whether the engine returned the opinion or an SEO summary of it.

The 7-day leaderboard on the HTML page is marked `data-markdown-ignore`. Those numbers are computed in the browser from [history.jsonl](data/history.jsonl). They are not sample copy. Do not invent live scores. The live dashboard, including per-query judgements, is on the [home leaderboards](index.md).

NEEDLE is an MIT-licensed benchmark from [Keenable](https://keenable.ai). Cite [DOI 10.5281/zenodo.22095155](https://doi.org/10.5281/zenodo.22095155).
