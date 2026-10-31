import collections
import glob
import json
import math
import sys

audit_dir, out_path = sys.argv[1], sys.argv[2]
sample = {s["id"]: s for s in json.load(open(f"{audit_dir}/sample.json"))}
labels = {}
for f in sorted(glob.glob(f"{audit_dir}/labels_part*.json")):
    for row in json.load(open(f)):
        labels[int(row["id"])] = row["label"]
missing = sorted(set(sample) - set(labels))
assert not missing, missing[:10]


def wilson(k, n, z=1.96):
    if not n:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


res = {}
for kind in ("money_exact", "money_reading", "other_field", "all"):
    ids = [i for i in sample if kind == "all" or sample[i]["kind"] == kind]
    n = len(ids)
    yes = sum(labels[i] == "yes" for i in ids)
    unclear = sum(labels[i] == "unclear" for i in ids)
    lo, hi = wilson(yes, n)
    res[kind] = {"n": n, "yes": yes, "no": n - yes - unclear, "unclear": unclear, "precision": yes / n if n else None, "wilson": (lo, hi)}
    print(f"{kind:14s} n {n:3d} yes {yes:3d} unclear {unclear:2d} precision {yes / n if n else 0:.3f} [{lo:.2f}, {hi:.2f}]")
by_engine = collections.defaultdict(lambda: [0, 0])
for i, s in sample.items():
    if s["kind"].startswith("money"):
        by_engine[s["engine"]][1] += 1
        by_engine[s["engine"]][0] += labels[i] == "yes"
res["money_by_engine"] = {e: {"yes": v[0], "n": v[1]} for e, v in by_engine.items()}
print("money precision by engine:", {e: f"{v[0]}/{v[1]}" for e, v in sorted(by_engine.items(), key=lambda kv: -kv[1][1])})
json.dump(res, open(out_path, "w"), indent=1)
