import json
import sys

hist, matched_json, out = sys.argv[1:4]
fixes = {}
for bench, ts, engine, n, mean, acc, svc, hist_n, hist_mean, _, _ in json.load(open(matched_json))["row_mismatches"]:
    assert abs((mean or 0) * n - (hist_mean or 0) * (hist_n or 0)) < 1e-6, (bench, ts, engine)
    fixes[(bench, ts, engine)] = (n, mean, acc, svc)

rows = [json.loads(line) for line in open(hist) if line.strip()]
metric = {"news": "ndcg", "agentic_rare": "ndcg"}
changed = 0
for r in rows:
    key = (r["bench"], r["ts"], r["engine"])
    if key not in fixes:
        continue
    n, mean, acc, svc = fixes.pop(key)
    changed += r["num_scored"] != n
    r["num_scored"] = n
    r[metric[r["bench"]]] = mean
    r["account_errors"] = acc
    r["service_errors"] = svc
assert not fixes, list(fixes)[:5]
open(out, "w").write("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))
print(f"Wrote {len(rows)} rows; {changed} rows drop account-side failures from the mean")
