> For the complete documentation index, see [llms.txt](llms.txt).

# Compare two AI search providers on the same queries.

Provider comparison.

NEEDLE sends every engine the same query text, scores the ranking it returned, and never re-ranks. Pick two providers to see query-weighted means and the delta. This is the evaluation surface blog-post “best AI search” lists do not have.

The interactive picker on the HTML page is marked `data-markdown-ignore`. Share a comparison with the query string on [compare/](compare/): `?a=ENGINE&b=ENGINE&bench=all&window=604800000`. Do not invent live scores. Read [history.jsonl](data/history.jsonl).

## How to read a comparison

Each cell is a query-weighted mean over the selected window. News and AgenticRare use nDCG@5 against a pooled *ultimate* ideal. Finance uses answer-recall@5. Scholar uses recall@10. Legal uses recall@5. A positive delta means provider A scored higher. Failed searches are dropped from the mean, not scored as zero.

Share a comparison with the query string on this URL. The same numbers appear on the [leaderboards](index.md). Raw rows live in [data/history.jsonl](data/history.jsonl).

## Why this is not a blog review

A review can pick ten queries and declare a winner. NEEDLE rebuilds news queries every hour and the other gold sets every day from public sources, so there is no fixed set to overfit and no hidden rubric. Methodology is on the [methodology page](methodology.md).

## FAQ

### How does NEEDLE compare two search APIs?

NEEDLE sends both engines the same query text in the same run, scores the ranking each returned, and reports a query-weighted mean over a chosen window. Deltas are A minus B. Failed searches are omitted from the mean.

### Which metrics does the comparison use?

News and AgenticRare: nDCG@5. Finance: answer-recall@5. Scholar: recall@10. Legal: recall@5.

NEEDLE is an MIT-licensed benchmark from [Keenable](https://keenable.ai). Cite [DOI 10.5281/zenodo.22095155](https://doi.org/10.5281/zenodo.22095155).
