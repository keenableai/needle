import collections
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import account_side  # noqa: E402

site, here = sys.argv[1], os.path.dirname(os.path.abspath(__file__))
LO, HI = "2026-10-17", "2026-10-30"
KEEP = "keenable exa google bing brave brave-llmcontext parallel perplexity tavily linkup tinyfish octen ceramic you firecrawl kagi jina context deepseek claude-search chatgpt-search".split()
labels = {x["id"]: x["label"] for x in json.load(open(os.path.join(here, "audit", "caselaw_identity", "labels.json")))}
sample = json.load(open(os.path.join(here, "audit", "caselaw_identity", "sample.json")))
frac = collections.defaultdict(lambda: [0, 0])
for i, x in enumerate(sample):
    frac[x["engine"]][1] += 1
    frac[x["engine"]][0] += labels[i] == "target"
pooled = sum(v[0] for v in frac.values()) / sum(v[1] for v in frac.values())
n = sum(v[1] for v in frac.values())
z = 1.96
p = pooled
wl = (p + z * z / (2 * n) - z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5) / (1 + z * z / n)
wh = (p + z * z / (2 * n) + z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5) / (1 + z * z / n)

hits = collections.defaultdict(lambda: {"caselaw": [0, 0], "code": [0, 0]})
for d in sorted(glob.glob(os.path.join(site, "hflegal", "*"))):
    name = os.path.basename(d)
    if not (LO <= name[:10] < HI) or not os.path.exists(os.path.join(d, "legal.json")):
        continue
    rep = json.load(open(os.path.join(d, "legal.json")))
    for e in KEEP:
        if e not in rep["engines"]:
            continue
        pth = os.path.join(d, rep["engines"][e].get("per_query_path", ""))
        if not os.path.isfile(pth):
            continue
        for q in json.load(open(pth))["per_query"]:
            if q.get("search_error") and account_side(q["search_error"]):
                continue
            b = "caselaw" if q.get("bucket") == "caselaw" else "code"
            hits[e][b][1] += 1
            hits[e][b][0] += q.get("hit_rank") is not None

rows = []
for e in KEEP:
    if e not in hits:
        continue
    hc, nc = hits[e]["caselaw"]
    hf, nf = hits[e]["code"]
    ntot = nc + nf
    rec = (hc + hf) / ntot
    pooled_rec = (pooled * hc + hf) / ntot
    lo_rec, hi_rec = (wl * hc + hf) / ntot, (wh * hc + hf) / ntot
    fe = frac[e][0] / frac[e][1] if frac[e][1] else pooled
    own_rec = (fe * hc + hf) / ntot
    rows.append((e, rec, pooled_rec, lo_rec, hi_rec, own_rec, fe, nc, nf))
rows.sort(key=lambda r: -r[1])
order_rec = [r[0] for r in rows]
order_pooled = [r[0] for r in sorted(rows, key=lambda r: -r[2])]
order_own = [r[0] for r in sorted(rows, key=lambda r: -r[5])]


def tau(a, b):
    c = d = 0
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            x = (a.index(a[i]) - a.index(a[j])) * (b.index(a[i]) - b.index(a[j]))
            c += x > 0
            d += x < 0
    return (c - d) / (c + d)


print(f"pooled target fraction {pooled:.2f} (Wilson {wl:.2f}-{wh:.2f}), caselaw queries per engine {rows[0][7]}, CFR {rows[0][8]}")
for r in rows:
    print(f"{r[0]:17s} legal R@5 {r[1]:.3f} -> target-only pooled {r[2]:.3f} [{r[3]:.3f},{r[4]:.3f}]  own-fraction {r[5]:.3f} (f={r[6]:.2f})")
print("drop pooled: %.3f to %.3f" % (min(r[1] - r[2] for r in rows), max(r[1] - r[2] for r in rows)))
print("tau_b order reported vs pooled-corrected %.3f, vs own-fraction %.3f" % (tau(order_rec, order_pooled), tau(order_rec, order_own)))
print("own-fraction order:", order_own)
json.dump([dict(zip(("engine", "recall", "target_pooled", "target_lo", "target_hi", "target_own", "own_fraction", "n_caselaw", "n_cfr"), r)) for r in rows],
          open(os.path.join(here, "audit", "legal_target_only.json"), "w"), indent=1)
