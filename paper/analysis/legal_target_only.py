import collections
import glob
import json
import os
import sys

from common import KEEP, order_tau

from needle.shared.search.errors import account_side

site, here = sys.argv[1], os.path.dirname(os.path.abspath(__file__))
RUNS = set(json.load(open(os.path.join(here, "audit", "adjacent_pairs.json")))["runs"])
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
    if name[:13] + ":" + name[13:15] + "Z" not in RUNS or not os.path.exists(os.path.join(d, "legal.json")):
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
print(f"pooled target fraction {pooled:.2f} (Wilson {wl:.2f}-{wh:.2f}), caselaw queries per engine {rows[0][7]}, CFR {rows[0][8]}")
for r in rows:
    print(f"{r[0]:17s} legal R@5 {r[1]:.3f} -> target-only pooled {r[2]:.3f} [{r[3]:.3f},{r[4]:.3f}]  own-fraction {r[5]:.3f} (f={r[6]:.2f})")
print(f"drop pooled: {min(r[1] - r[2] for r in rows):.3f} to {max(r[1] - r[2] for r in rows):.3f}")
print(f"tau_b order reported vs pooled-corrected {order_tau(order_rec, order_pooled):.3f}, vs own-fraction {order_tau(order_rec, order_own):.3f}")
print("own-fraction order:", order_own)
json.dump([dict(zip(("engine", "recall", "target_pooled", "target_lo", "target_hi", "target_own", "own_fraction", "n_caselaw", "n_cfr"), r, strict=True)) for r in rows],
          open(os.path.join(here, "audit", "legal_target_only.json"), "w"), indent=1)
