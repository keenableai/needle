import glob
import json
import random
import sys
from collections import Counter

history, out_history, pattern, audit_dir = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
rng = random.Random(5)
rows, new = [], []
for f in sorted(glob.glob(pattern)):
    d = json.load(open(f))
    rows.extend(d["rows"])
    new.extend(d["new_hits"])
ts = {r["ts"] for r in rows}
out = []
replaced = 0
for line in open(history):
    if not line.strip():
        continue
    r = json.loads(line)
    if r["bench"] == "finance" and r["ts"] in ts:
        replaced += 1
        continue
    out.append(r)
out.extend(rows)
with open(out_history, "w") as f:
    for r in out:
        f.write(json.dumps(r) + "\n")
print("replaced", replaced, "rows with", len(rows), "; new table-figure hits", len(new), "by field", Counter(h["field"] for h in new))
print("new hits by engine", Counter(h["engine"] for h in new).most_common())
sample = rng.sample(new, min(80, len(new)))
for i, h in enumerate(sample):
    h["id"] = i
import os
os.makedirs(audit_dir, exist_ok=True)
json.dump(sample[:40], open(f"{audit_dir}/v2hits_part1.json", "w"), indent=1)
json.dump(sample[40:], open(f"{audit_dir}/v2hits_part2.json", "w"), indent=1)
json.dump(sample, open(f"{audit_dir}/v2hits_all.json", "w"), indent=1)
print("audit sample", len(sample))
