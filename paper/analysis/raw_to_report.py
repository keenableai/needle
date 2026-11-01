import json
import re
import sys

from needle.finance.cli import _gold_ok, _gold_query
from needle.finance.score import result_answers
from needle.shared.cli import load_gold_rows
from needle.shared.recall import first_rank
from needle.shared.search import DEFAULT_SNIPPET_CHARS, SearchResult, capped_snippet

queries_path, raw_path, out_path = sys.argv[1:4]
rows = load_gold_rows(queries_path, bench="finance", gold_ok=_gold_ok)
gold = {r["query_text"]: _gold_query(r) for r in rows}
raw = json.load(open(raw_path))
WS = re.compile(r"[ \t ]{2,}")


def collapse(s):
    return WS.sub(" ", s) if s else s


engines = {e: {"per_query": [], "search_errors": 0, "num_scored": 0} for e in raw["engines"]}
for q in raw["queries"]:
    g = gold[q["query"]]
    for e, s in q["by_engine"].items():
        pq = {"query": q["query"], "field": g.field, "value": g.value, "hit_rank": None, "results": [], "search_error": s["error"], "queried_at": s["queried_at"]}
        if s["error"] is None:
            engines[e]["num_scored"] += 1
            results = [SearchResult(url=r["url"], title=collapse(r.get("title")), snippet=collapse(r.get("snippet")), published_date=r.get("published_date")) for r in s["results"][:5]]
            det = [result_answers(g, r, snippet_chars=DEFAULT_SNIPPET_CHARS) for r in results]
            pq["hit_rank"] = first_rank(det)
            pq["results"] = [{"url": r.url, "title": r.title, "snippet": capped_snippet(r, DEFAULT_SNIPPET_CHARS), "det_match": d} for r, d in zip(results, det)]
        else:
            engines[e]["search_errors"] += 1
        engines[e]["per_query"].append(pq)
for e, v in engines.items():
    scored = [p for p in v["per_query"] if p["search_error"] is None]
    v["recall_at_k"] = sum(p["hit_rank"] is not None for p in scored) / len(scored) if scored else None
    print(f"{e:16s} production-rule recall {v['recall_at_k']:.3f} scored {len(scored)} errs {v['search_errors']}")
json.dump({"num_queries": len(raw["queries"]), "num_results": 5, "snippet_chars": DEFAULT_SNIPPET_CHARS, "engines": engines}, open(out_path, "w"))
print("wrote", out_path)
