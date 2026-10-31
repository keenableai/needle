import json
import random
import sys
from collections import Counter
from pathlib import Path

fin_dir, sch_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
out_dir.mkdir(parents=True, exist_ok=True)
rng = random.Random(21)

fin_pool = []
scored_q = Counter()
for run in sorted(p for p in fin_dir.iterdir() if p.is_dir()):
    gold = {}
    for line in open(run / "gold.jsonl"):
        if line.strip():
            g = json.loads(line)
            gold[g["query_text"]] = g
    rep = json.load(open(run / "recall.json"))
    first = True
    for eng, e in rep["engines"].items():
        p = run / e.get("per_query_path", "")
        if eng == "ultimate" or not p.exists():
            continue
        for pq in json.load(open(p))["per_query"]:
            if first:
                scored_q[pq["query"]] += 1
            g = gold.get(pq["query"])
            if g is None or pq["search_error"] is not None or g["gold"]["field_type"] != "money":
                continue
            if pq["det_rank"] is None and pq["results"]:
                fin_pool.append((run.name, eng, pq, g))
        first = False
print("finance scored query-runs (one engine)", sum(scored_q.values()), "unique", len(scored_q), "repeat share %.3f" % (sum(v - 1 for v in scored_q.values()) / sum(scored_q.values())))
print("finance money misses pool", len(fin_pool))
fin_items = []
for run, eng, pq, g in rng.sample(fin_pool, 100):
    prov = json.loads(g["query_origin"])["provenance"]
    fin_items.append({
        "id": len(fin_items), "run": run, "engine": eng, "query": pq["query"], "company": prov.get("entity"),
        "field": g["gold"]["field"], "gold_value": g["gold"]["value"], "aliases": g["gold"].get("aliases"),
        "results": [{"rank": i + 1, "title": r.get("title"), "url": r["url"], "snippet": (r.get("snippet") or "")[:1200]} for i, r in enumerate(pq["results"][:5])],
    })

sch_pool = []
for run in sorted(p for p in sch_dir.iterdir() if p.is_dir() and (p / "scholar.json").exists()):
    meta = {}
    for line in open(run / "scholar.jsonl"):
        if line.strip():
            g = json.loads(line)
            o = json.loads(g["query_origin"])
            meta[g["query_text"]] = (o["bucket"], o["provenance"]["title"], o["provenance"].get("url"))
    rep = json.load(open(run / "scholar.json"))
    for eng, e in rep["engines"].items():
        p = run / e.get("per_query_path", "")
        if eng == "ultimate" or not p.exists():
            continue
        for pq in json.load(open(p))["per_query"]:
            m = meta.get(pq["query"])
            if m is None or pq.get("search_error") is not None or m[0] not in ("body", "clue"):
                continue
            if pq.get("hit_rank") is None and pq["results"]:
                sch_pool.append((run.name, eng, pq, m))
print("scholar body/question misses pool", len(sch_pool))
sch_items = []
for run, eng, pq, (bucket, title, url) in rng.sample(sch_pool, 100):
    sch_items.append({
        "id": len(sch_items), "run": run, "engine": eng, "bucket": bucket, "query": pq["query"], "target_title": title,
        "results": [{"rank": i + 1, "title": r.get("title"), "url": r["url"], "snippet": (r.get("snippet") or "")[:500]} for i, r in enumerate(pq["results"][:10])],
    })
for name, items in (("finance", fin_items), ("scholar", sch_items)):
    for part in (1, 2):
        chunk = items[(part - 1) * 50:part * 50]
        json.dump(chunk, open(out_dir / f"{name}_part{part}.json", "w"), indent=1)
    json.dump(items, open(out_dir / f"{name}_all.json", "w"), indent=1)
print("written", len(fin_items), len(sch_items))
