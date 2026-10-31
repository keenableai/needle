import json
import sys
from collections import defaultdict
from pathlib import Path

hf_dir = Path(sys.argv[1])
runs = sorted(p for p in hf_dir.iterdir() if p.is_dir())
hits = defaultdict(lambda: defaultdict(lambda: [0, 0]))
ceiling = defaultdict(lambda: [0, 0])
nq = defaultdict(int)
for run in runs:
    syntax = {}
    for line in open(run / "gold.jsonl"):
        if line.strip():
            g = json.loads(line)
            o = json.loads(g["query_origin"])
            grp = "filing" if g["gold"]["field"] == "filing" else "fact"
            syntax[g["query_text"]] = f"{grp}/{o.get('syntax', 'plain')}"
    rep = json.load(open(run / "recall.json"))
    per_q_any = defaultdict(bool)
    seen_q = set()
    for eng, e in rep["engines"].items():
        if eng == "ultimate" or "per_query_path" not in e:
            continue
        p = run / e["per_query_path"]
        if not p.exists():
            continue
        for pq in json.load(open(p))["per_query"]:
            if pq["search_error"] is not None:
                continue
            sx = syntax.get(pq["query"], "plain")
            hit = pq["hit_rank"] is not None
            hits[eng][sx][0] += hit
            hits[eng][sx][1] += 1
            per_q_any[pq["query"]] |= hit
            seen_q.add(pq["query"])
    for q in seen_q:
        sx = syntax.get(q, "plain")
        ceiling[sx][0] += per_q_any[q]
        ceiling[sx][1] += 1
        nq[sx] += 1

syntaxes = sorted(nq, key=lambda s: -nq[s])
print("queries by syntax", {s: nq[s] for s in syntaxes})
print("ceiling", {s: round(ceiling[s][0] / ceiling[s][1], 3) for s in syntaxes})
rows = []
for eng in hits:
    r = {s: (hits[eng][s][0] / hits[eng][s][1] if hits[eng][s][1] else None) for s in syntaxes}
    rows.append((eng, r))
rows.sort(key=lambda x: -(x[1]["fact/plain"] or 0))
print(f"{'engine':18s}" + "".join(f"{s:>9s}" for s in syntaxes))
for eng, r in rows:
    print(f"{eng:18s}" + "".join(f"{(r[s] if r[s] is not None else float('nan')):9.3f}" for s in syntaxes))
mean = {s: sum(r[s] for _, r in rows if r[s] is not None) / sum(1 for _, r in rows if r[s] is not None) for s in syntaxes}
print("mean over engines", {s: round(v, 3) for s, v in mean.items()})
share = {s: round(mean[s] / (ceiling[s][0] / ceiling[s][1]), 3) for s in syntaxes}
print("mean share of ceiling", share)
