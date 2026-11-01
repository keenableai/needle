import collections
import glob
import json
import os

A = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit", "fresh")
old = json.load(open(os.path.join(A, "sample.json")))
new = json.load(open(os.path.join(A, "dashboard_sample.json")))
labels = {}
for f in sorted(glob.glob(os.path.join(A, "labels_part*.json"))):
    for row in json.load(open(f)):
        labels[int(row["id"])] = row["label"]


def key(s):
    return s["engine"], s["query"], s["url"]


ok = {key(s): s for s in old if s["kind"] == "money_reading"}
nk = {key(s): s for s in new if s["kind"] == "money_reading"}
kept = [ok[k] for k in ok if k in nk]
by_engine = collections.defaultdict(collections.Counter)
for s in kept:
    by_engine[s["engine"]][labels[s["id"]]] += 1
out = {
    "old_reading": len(ok),
    "dashboard_reading": len(nk),
    "dropped": [{"engine": ok[k]["engine"], "query": ok[k]["query"], "label": labels[ok[k]["id"]]} for k in sorted(set(ok) - set(nk))],
    "added": [{"engine": nk[k]["engine"], "query": nk[k]["query"]} for k in sorted(set(nk) - set(ok))],
    "kept": dict(collections.Counter(labels[s["id"]] for s in kept)),
    "kept_by_engine": {e: dict(c) for e, c in sorted(by_engine.items())},
}
json.dump(out, open(os.path.join(A, "pool_diff.json"), "w"), indent=1)
print(out["old_reading"], out["dashboard_reading"], out["kept"])
