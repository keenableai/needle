import glob
import json
import sys

history, out_history = sys.argv[1], sys.argv[2]
rows = []
for f in sorted(glob.glob(sys.argv[3])):
    rows.extend(json.load(open(f)))
strict_ts = {r["ts"] for r in rows}
out = []
replaced = 0
for line in open(history):
    if not line.strip():
        continue
    r = json.loads(line)
    if r["bench"] == "finance" and r["ts"] in strict_ts:
        replaced += 1
        continue
    out.append(r)
out.extend(rows)
with open(out_history, "w") as f:
    for r in out:
        f.write(json.dumps(r) + "\n")
print("replaced", replaced, "finance rows with", len(rows), "strict rows over", len(strict_ts), "runs")
