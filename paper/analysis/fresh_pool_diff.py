import collections
import glob
import json
import os

from common import wilson

A = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit", "fresh")
labels = {}
for f in sorted(glob.glob(os.path.join(A, "labels_part*.json"))):
    for row in json.load(open(f)):
        labels[int(row["id"])] = row["label"]


def key(s):
    return s["engine"], s["query"], s["url"]


graded = {key(s): labels[s["id"]] for s in json.load(open(os.path.join(A, "sample.json"))) if s["kind"] == "money_reading"}
current = {key(s) for s in json.load(open(os.path.join(A, "dashboard_sample.json"))) if s["kind"] == "money_reading"}
both = sorted(set(graded) & current)


def counts(keys):
    c = collections.Counter(graded[k] for k in keys)
    return {"n": len(keys), "yes": c["yes"], "unclear": c["unclear"], "no": c["no"]}


by_engine = collections.defaultdict(list)
for k in both:
    by_engine[k[0]].append(k)
total = counts(both)
out = {
    "graded": len(graded),
    "current": len(current),
    "graded_current": {**total, "precision": total["yes"] / total["n"], "wilson": wilson(total["yes"], total["n"]),
                       "not_contradicted": (total["n"] - total["no"]) / total["n"]},
    "graded_current_by_engine": {e: counts(ks) for e, ks in sorted(by_engine.items())},
    "graded_not_current": [{"engine": k[0], "query": k[1], "label": graded[k]} for k in sorted(set(graded) - current)],
    "current_not_graded": [{"engine": k[0], "query": k[1]} for k in sorted(current - set(graded))],
}
json.dump(out, open(os.path.join(A, "pool_diff.json"), "w"), indent=1)
print(out["graded"], out["current"], out["graded_current"])
for e, c in out["graded_current_by_engine"].items():
    print(f"  {e:16s} {c['yes']}/{c['n']} unclear {c['unclear']} no {c['no']}")
