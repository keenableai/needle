import json
import random
import sys
from collections import defaultdict
from pathlib import Path

from needle.shared.metrics import apply_redundancy_penalties, dcg_at_k, normalize_url

full_dir, trunc_dir, out_path = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
rng = random.Random(13)
key = {int(k): v for k, v in json.load(open(full_dir / "key.json")).items()}
queries = json.load(open(full_dir / "queries.json"))


def load(d):
    out = {}
    for f in sorted(d.glob("labels_part*.json")):
        for row in json.load(open(f)):
            out[int(row["id"])] = int(row["rating"])
    return out


opus, trunc = load(full_dir), load(trunc_dir)


def per_query(rating_of):
    rows = []
    for q in queries:
        pool, eng = {}, {}
        for name, m in q["engines"].items():
            if any(i not in rating_of for i in m["positions"]):
                continue
            urls = [key[i]["url"] for i in m["positions"]]
            rs = [rating_of[i] for i in m["positions"]]
            for u, r in zip(urls, rs):
                pool[normalize_url(u)] = max(pool.get(normalize_url(u), 0), r)
            eng[name] = apply_redundancy_penalties(urls, rs, query_text=q["query"])
        idcg = dcg_at_k(sorted(pool.values(), reverse=True))
        rows.append({name: dcg_at_k(rs) / idcg for name, rs in eng.items()} if idcg > 0 else {})
    return rows


pf, pt = per_query(opus), per_query(trunc)
names = sorted(set.intersection(*[set(r) for r in pf if r]) & set.intersection(*[set(r) for r in pt if r]))


def shares(rows, idx):
    out = {}
    for e in names:
        vals = [rows[i][e] for i in idx if rows[i] and e in rows[i]]
        out[e] = sum(vals) / len(vals)
    return out


def tau_b(a, b):
    c = d = 0
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            x = (a[i] - a[j]) * (b[i] - b[j])
            c += x > 0
            d += x < 0
    return (c - d) / (c + d) if c + d else float("nan")


idx = list(range(len(queries)))
sf, st = shares(pf, idx), shares(pt, idx)
lead_f = sorted(names, key=lambda e: -sf[e])
print("engines", len(names), "queries", len(queries))
print("full order:", lead_f[:5], "...", lead_f[-3:])
print("trunc order:", sorted(names, key=lambda e: -st[e])[:5])
boots = []
for _ in range(2000):
    samp = [rng.randrange(len(queries)) for _ in queries]
    a, b = shares(pf, samp), shares(pt, samp)
    boots.append({"tau": tau_b([a[e] for e in names], [b[e] for e in names]), "mad": sum(abs(a[e] - b[e]) for e in names) / len(names),
                  "d": {e: b[e] - a[e] for e in names}, "lead_gap": (b[lead_f[0]] - b[lead_f[1]]), "lead_gap_full": (a[lead_f[0]] - a[lead_f[1]])})


def ci(vals):
    v = sorted(vals)
    return v[int(.025 * len(v))], v[int(.975 * len(v))]


print("tau_b %.3f ci %s" % (tau_b([sf[e] for e in names], [st[e] for e in names]), tuple(round(x, 2) for x in ci([b["tau"] for b in boots]))))
print("mean|d| %.3f ci %s" % (sum(abs(sf[e] - st[e]) for e in names) / len(names), tuple(round(x, 3) for x in ci([b["mad"] for b in boots]))))
res = {"tau_b": tau_b([sf[e] for e in names], [st[e] for e in names]), "tau_ci": ci([b["tau"] for b in boots]), "mad": sum(abs(sf[e] - st[e]) for e in names) / len(names), "mad_ci": ci([b["mad"] for b in boots]), "engines": {}}
for e in sorted(names, key=lambda e: -abs(st[e] - sf[e])):
    lo, hi = ci([b["d"][e] for b in boots])
    res["engines"][e] = {"full": sf[e], "trunc": st[e], "delta": st[e] - sf[e], "ci": (lo, hi)}
    if abs(st[e] - sf[e]) > 0.08:
        print(f"  {e:18s} full {sf[e]:.3f} trunc {st[e]:.3f} d {st[e]-sf[e]:+.3f} ci [{lo:+.3f},{hi:+.3f}]")
print("leader %s vs %s: full gap %+.3f ci %s; trunc gap %+.3f ci %s" % (lead_f[0], lead_f[1], sf[lead_f[0]] - sf[lead_f[1]], tuple(round(x, 3) for x in ci([b["lead_gap_full"] for b in boots])), st[lead_f[0]] - st[lead_f[1]], tuple(round(x, 3) for x in ci([b["lead_gap"] for b in boots]))))
json.dump(res, open(out_path, "w"), indent=1)
