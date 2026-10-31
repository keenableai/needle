# Finance hit audit guideline

Each item is one search result that a deterministic matcher counted as answering a finance query. You decide whether the result's text really states the answer. Judge only the `title` and `snippet`; do not open the URL and do not use outside knowledge of the true value, except to recognize that two names or formats refer to the same thing.

## What you see per item

- `query`: the searcher's query. It names a company and asks for one fact.
- `company`: the company the gold value belongs to.
- `field`: the fact asked for (for example `net_income`, `eps_diluted`, `operating_income`, `employees`, `ceo`, `founded_year`, `hq_country`, `ticker`, `lei`, `website`).
- `gold`, `aliases`: the gold value and accepted alternative forms. Money values are in US dollars; `eps_diluted` is dollars per share.
- `rank`, `title`, `url`, `snippet`: the result as the engine returned it.

## Labels

- `yes`: the title or snippet states the gold value for this company and this fact, for the period the query names if it names one. A different unit or scale that denotes the same amount counts (for example "$10,999 million" for 10999000000; a table figure "10,999" under a "$ in millions" heading; "(1,234)" for a loss of 1,234). A rounded figure within 0.1% counts.
- `no`: the number or name in the text is a different fact, a different period, a different company, or a coincidental match (for example a share count, a percentage, a date, a different quarter or a prior-year figure when the query asks for the current one).
- `unclear`: the text contains the gold figure but you cannot tell from the title and snippet which fact, period or company it belongs to.

## Output

Write a JSON list, one object per item, in the order given:

```json
[{"id": 17, "label": "yes", "reason": "states Q1 2025 net income of $10,999 million"}]
```

`reason` is at most 15 words. Label every item in the part file. Do not skip items and do not add fields.
