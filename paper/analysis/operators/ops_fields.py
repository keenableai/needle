import json
import sys
from collections import defaultdict
from pathlib import Path

hf_dir = Path(sys.argv[1])
runs = sorted(p for p in hf_dir.iterdir() if p.is_dir())
tot = defaultdict(lambda: [0, 0])
ceil = defaultdict(lambda: [0, 0])
per_engine = defaultdict(lambda: defaultdict(lambda: [0, 0]))
for run in runs:
    meta = {}
    for line in open(run / "gold.jsonl"):
        if line.strip():
            g = json.loads(line)
            o = json.loads(g["query_origin"])
            if g["gold"]["field"] == "filing":
                continue
            meta[g["query_text"]] = (g["gold"]["field_type"], o.get("syntax", "plain"))
    rep = json.load(open(run / "recall.json"))
    any_hit = defaultdict(bool)
    for eng, e in rep["engines"].items():
        if eng == "ultimate" or "per_query_path" not in e:
            continue
        p = run / e["per_query_path"]
        if not p.exists():
            continue
        for pq in json.load(open(p))["per_query"]:
            m = meta.get(pq["query"])
            if m is None or pq["search_error"] is not None:
                continue
            hit = pq["hit_rank"] is not None
            tot[m][0] += hit
            tot[m][1] += 1
            per_engine[eng][m[1]][0] += hit
            per_engine[eng][m[1]][1] += 1
            any_hit[pq["query"]] |= hit
    for q, m in meta.items():
        if q in any_hit:
            ceil[m][0] += any_hit[q]
            ceil[m][1] += 1

fts = sorted({k[0] for k in tot})
print(f"{'field_type':14s} {'plain n':>8s} {'plain':>7s} {'quoted n':>9s} {'quoted':>7s} {'ceil p':>7s} {'ceil q':>7s}")
for ft in fts:
    p, q = tot[(ft, "plain")], tot[(ft, "quoted")]
    cp, cq = ceil[(ft, "plain")], ceil[(ft, "quoted")]
    print(f"{ft:14s} {p[1]:8d} {p[0]/max(1,p[1]):7.3f} {q[1]:9d} {q[0]/max(1,q[1]):7.3f} {cp[0]/max(1,cp[1]):7.3f} {cq[0]/max(1,cq[1]):7.3f}")
print("engine gap (plain - quoted) on fact queries:")
gaps = []
for eng, d in per_engine.items():
    if d["plain"][1] and d["quoted"][1]:
        gaps.append((d["plain"][0] / d["plain"][1] - d["quoted"][0] / d["quoted"][1], eng, d["plain"][0] / d["plain"][1], d["quoted"][0] / d["quoted"][1]))
for g, eng, p, q in sorted(gaps):
    print(f"  {eng:18s} plain={p:.3f} quoted={q:.3f} gap={g:+.3f}")
