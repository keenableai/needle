import collections
import json
import random
import sys
from pathlib import Path

hf_dir, out_json, n = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
rng = random.Random(31)
pool = []
for run in sorted(p for p in hf_dir.iterdir() if p.is_dir() and (p / "legal.json").exists()):
    gold = {}
    for line in open(run / "legal.jsonl"):
        if line.strip():
            g = json.loads(line)
            gold[g["query_text"]] = json.loads(g["gold"]) if isinstance(g["gold"], str) else g["gold"]
    rep = json.load(open(run / "legal.json"))
    for eng, e in rep["engines"].items():
        p = run / e.get("per_query_path", "")
        if eng == "ultimate" or not p.exists():
            continue
        for pq in json.load(open(p))["per_query"]:
            if pq.get("bucket") != "caselaw" or pq.get("hit_rank") is None:
                continue
            g = gold.get(pq["query"])
            if not g:
                continue
            r = pq["results"][int(pq["hit_rank"]) - 1]
            pool.append({"run": run.name, "engine": eng, "query": pq["query"], "case_name": g.get("case_name"), "court": g.get("court"), "date_filed": g.get("date_filed"), "docket": (g.get("ids") or {}).get("docket"), "title": r.get("title"), "url": r["url"], "snippet": (r.get("snippet") or "")[:1200]})
by_engine = collections.defaultdict(list)
for x in pool:
    by_engine[x["engine"]].append(x)
per = max(1, n // len(by_engine))
sample = []
for eng in sorted(by_engine):
    sample += rng.sample(by_engine[eng], min(per, len(by_engine[eng])))
rng.shuffle(sample)
for i, x in enumerate(sample):
    x["id"] = i
json.dump(sample, open(out_json, "w"), indent=1)
json.dump([{k: v for k, v in x.items() if k not in ("engine", "run")} for x in sample], open(out_json.replace(".json", "_blind.json"), "w"), indent=1)
print("caselaw hits pool", len(pool), "engines", len(by_engine), "sampled", len(sample), "per engine", per)
