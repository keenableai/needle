import json
import random
import sys
from collections import Counter
from pathlib import Path

hf_dir, sweep_json, sample_json, out_json = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
bs = json.load(open(sweep_json))
ENGINES = list(bs["sweep"]["money"][str(bs["reference"]["money"])]["per_engine"])
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
for key, n in (("money", 50), ("other", 20)):
    for run_id, eng, q, g, rank, r in rng.sample(pool[key], min(n, len(pool[key]))):
        sample.append({
            "id": len(sample), "kind": f"upgrade_{key}", "run": run_id, "engine": eng, "query": q,
            "field": g["field"], "field_type": g["field_type"], "gold": g["value"], "aliases": g["aliases"],
            "rank": rank, "title": r.get("title"), "url": r["url"], "snippet": (r.get("snippet") or "")[:700],
        })
json.dump(sample, open(out_json, "w"), indent=1)
print("pool", {k: len(v) for k, v in pool.items()}, "sample", len(sample), Counter(s["kind"] for s in sample))
