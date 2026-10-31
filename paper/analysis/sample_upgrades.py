import json
import random
import sys
from collections import Counter
from pathlib import Path

hf_dir, sweep_json, sample_json, out_json = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
ENGINES = list(json.load(open(sweep_json))["sweep"]["money"]["0.02"]["per_engine"])
rng = random.Random(11)

gold = {}
runs = sorted(p for p in hf_dir.iterdir() if p.is_dir())
for run in runs:
    for line in open(run / "gold.jsonl"):
        if line.strip():
            g = json.loads(line)
            gold[g["query_text"]] = g["gold"]

pool = {"money": [], "other": []}
for run in runs:
    for eng in ENGINES:
        p = run / "recall" / f"{eng}.json"
        if not p.exists():
            continue
        for pq in json.load(open(p))["per_query"]:
            if pq["search_error"] is not None or pq["det_rank"] is not None or pq["hit_rank"] is None:
                continue
            g = gold.get(pq["query"])
            if g is None:
                continue
            r = pq["results"][pq["hit_rank"] - 1]
            key = "money" if g["field_type"] == "money" else "other"
            pool[key].append((run.name, eng, pq["query"], g, pq["hit_rank"], r))

sample = json.load(open(sample_json))
start = len(sample)
for key, n in (("money", 50), ("other", 20)):
    for run_id, eng, q, g, rank, r in rng.sample(pool[key], min(n, len(pool[key]))):
        sample.append({
            "id": len(sample), "kind": f"upgrade_{key}", "run": run_id, "engine": eng, "query": q,
            "field": g["field"], "field_type": g["field_type"], "gold": g["value"], "aliases": g["aliases"],
            "rank": rank, "title": r.get("title"), "url": r["url"], "snippet": (r.get("snippet") or "")[:700],
        })
json.dump(sample, open(out_json, "w"), indent=1)
print("pool", {k: len(v) for k, v in pool.items()}, "sample", len(sample), Counter(s["kind"] for s in sample))

def tau_b(a, b):
    n = len(a); c = d = ta = tb = 0
    for i in range(n):
        for j in range(i + 1, n):
            x, y = a[i] - a[j], b[i] - b[j]
            if x == 0 and y == 0:
                continue
            if x == 0:
                ta += 1
            elif y == 0:
                tb += 1
            elif x * y > 0:
                c += 1
            else:
                d += 1
    return (c - d) / (((c + d + ta) * (c + d + tb)) ** 0.5)

sw = json.load(open(sweep_json))["sweep"]
for ft, default in (("money", "0.02"), ("numeric_band", "0.15")):
    base = sw[ft][default]["per_engine"]
    engs = list(base)
    for t, v in sw[ft].items():
        vals = [v["per_engine"][e] for e in engs]
        print(ft, t, "recall %.3f" % v["recall"], "tau_b %.3f" % tau_b(vals, [base[e] for e in engs]))
