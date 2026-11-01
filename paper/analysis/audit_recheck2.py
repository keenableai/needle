import collections
import json
import sys
from pathlib import Path

from needle.shared.search import DEFAULT_SNIPPET_CHARS, SearchResult, capped_snippet

hf_dir, sample_json, out_json = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
label_files = sys.argv[4:]
sample = {s["id"]: s for s in json.load(open(sample_json))}
nos = []
for p in label_files:
    nos += [int(x["id"]) for x in json.load(open(p)) if x["label"] == "no" and not sample[int(x["id"])]["kind"].startswith("upgrade")]
out = []
kinds = collections.Counter()
for i in sorted(nos):
    s = sample[i]
    pqs = json.load(open(hf_dir / s["run"] / "recall" / f"{s['engine']}.json"))["per_query"]
    pq = next(q for q in pqs if q["query"] == s["query"])
    r = next(r for r in pq["results"] if r["url"] == s["url"])
    kinds[s["kind"]] += 1
    out.append({"id": i, "kind": s["kind"], "query": s["query"], "field": s["field"], "field_type": s["field_type"], "gold": s["gold"], "aliases": s["aliases"], "title": r.get("title"), "url": r["url"], "snippet": capped_snippet(SearchResult(url=r["url"], snippet=r.get("snippet")), DEFAULT_SNIPPET_CHARS)})
json.dump(out, open(out_json, "w"), indent=1)
print("recheck items", len(out), dict(kinds), "mean snippet chars", sum(len(x["snippet"]) for x in out) // len(out))
