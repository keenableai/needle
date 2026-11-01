import collections
import json
import os
import sys

A = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, A)
from strict_v2 import gold_queries, gold_rows, prose_hit  # noqa: E402

from needle.finance.score import result_answers  # noqa: E402
from needle.shared.search import SearchResult  # noqa: E402

site = sys.argv[1]
items = json.load(open(os.path.join(A, "audit", "misses", "finance_all.json")))
labels = {x["id"]: x for p in ("finance_labels_part1.json", "finance_labels_part2.json") for x in json.load(open(os.path.join(A, "audit", "misses", p)))}
queries = {run: gold_queries(gold_rows(os.path.join(site, "hf", run, "gold.jsonl"))) for run in sorted({x["run"] for x in items})}
c = collections.Counter()
for x in items:
    q = queries[x["run"]][x["query"]]
    res = [SearchResult(url=r["url"], title=r.get("title") or "", snippet=r.get("snippet") or "") for r in x["results"][:5]]
    prod = any(result_answers(q, r, snippet_chars=0) for r in res)
    prose = any(prose_hit(q, {"url": r.url, "title": r.title, "snippet": r.snippet}) for r in res)
    c[" ".join((labels[x["id"]]["verdict"], "hit" if prod else "miss", "prose_hit" if prose else "prose_miss"))] += 1
json.dump(dict(sorted(c.items())), open(os.path.join(A, "audit", "misses", "recover.json"), "w"), indent=1)
for k, n in sorted(c.items()):
    print(k, n)
