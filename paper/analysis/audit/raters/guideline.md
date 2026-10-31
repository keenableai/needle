# Relevance assessment guideline

You are a relevance assessor for a web search evaluation. For each item you grade how well one web page meets the need behind one search query. The search engine that returned the page is hidden on purpose; do not try to guess it. Judge only what the page shows. Do not use your own knowledge of the correct answer, except to recognize that two names refer to the same thing.

## What you see per item

- `today`: the date the search ran. Judge freshness against this date, not against the current date.
- `query`: the searcher's query, exactly as typed.
- `url`, `title`, `snippet`: what the search engine returned.
- `page_excerpt`: the first part of the page, fetched later. It can be empty or broken (error page, cookie wall, login wall, unrelated boilerplate).

## Two grades per item

1. `snippet_grade`: grade from the URL, title and snippet only. Decide it before you read the page excerpt.
2. `page_grade`: grade from everything, including the page excerpt. If the excerpt is empty or broken, copy `snippet_grade` into `page_grade` and set `page_missing` to true.

## Scale

- 4, fully meets: the page answers the main need of the query directly and in depth, from a source a careful searcher would trust. The searcher can stop here.
- 3, highly meets: the page answers the main need, with small gaps, or from a less direct source.
- 2, somewhat meets: the page is on topic and useful but answers only part of the need, or mentions the subject only in passing.
- 1, marginally meets: the page is topic-adjacent and gives little or no usable information for this query.
- 0, fails: off topic, wrong entity, broken or empty page, a duplicate of another result for the same query, or a violated operator (see below).

## Rules that cap a grade

- Specific-answer queries (who, when, how much, which one): if the page does not contain the specific answer, the grade is at most 2. A page that credibly shows the premise is false counts as answering.
- Multi-item queries (A vs B, top 10, pros and cons): if the page covers fewer than half of the requested items, the grade is at most 2.
- Freshness: for queries about current events, a page that is clearly stale relative to `today` (an earlier edition of the event, superseded news) gets at most 2.
- Quoted phrases: a span in double quotes must appear word for word (case does not matter) in the title, snippet or page excerpt. If it does not, grade 0.
- `site:host`: the URL host must be that host or one of its subdomains. If it is not, grade 0.
- `after:` and `before:` dates: if the page shows a publication date outside the window, grade 0. If no date is visible, do not penalize.

## Output

Write a JSON list, one object per item, in the order given:

```json
[{"id": 17, "snippet_grade": 2, "page_grade": 3, "page_missing": false, "note": "page has the full table the snippet only hints at"}]
```

`note` is at most 15 words. Grade every item in the part file. Do not skip items and do not add fields.
