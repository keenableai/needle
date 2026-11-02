import json
import random
import sys
from pathlib import Path

from common import ci, spearman, tau_b

from needle.shared.metrics import apply_redundancy_penalties, dcg_at_k, normalize_url

MINQ = 6
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
            for u, r in zip(urls, rs, strict=True):
                pool[normalize_url(u)] = max(pool.get(normalize_url(u), 0), r)
            eng[name] = apply_redundancy_penalties(urls, rs, query_text=q["query"])
        idcg = dcg_at_k(sorted(pool.values(), reverse=True))
        rows.append({name: dcg_at_k(rs) / idcg for name, rs in eng.items()} if idcg > 0 else {})
    return rows


pf, pt = per_query(opus), per_query(trunc)
names = [e for e in sorted(set().union(*pf, *pt)) if all(sum(1 for r in p if e in r) >= MINQ for p in (pf, pt))]


def shares(rows, idx):
    out = {}
    for e in names:
        vals = [rows[i][e] for i in idx if e in rows[i]]
        out[e] = sum(vals) / len(vals)
    return out


def order(s):
    return sorted(names, key=lambda e: (-s[e], e))


def stats(a, b):
    x, y = [a[e] for e in names], [b[e] for e in names]
    return {"tau_b": tau_b(x, y), "spearman": spearman(x, y), "mad": sum(abs(p - q) for p, q in zip(x, y, strict=True)) / len(names)}


idx = list(range(len(queries)))
sf, st = shares(pf, idx), shares(pt, idx)
lead = {"full": order(sf)[:2], "trunc": order(st)[:2]}
point = stats(sf, st)
boots = []
for _ in range(2000):
    samp = [rng.randrange(len(queries)) for _ in queries]
    a, b = shares(pf, samp), shares(pt, samp)
    boots.append({**stats(a, b), "d": {e: b[e] - a[e] for e in names},
                  "gap": {"full": a[lead["full"][0]] - a[lead["full"][1]], "trunc": b[lead["trunc"][0]] - b[lead["trunc"][1]]}})

res = {"queries": len(queries), "minq": MINQ, "resamples": len(boots), "order_full": order(sf), "order_trunc": order(st)}
for k in ("tau_b", "spearman", "mad"):
    res[k] = point[k]
    res[k + "_ci"] = ci([b[k] for b in boots])
res["leader_gap"] = {}
for cond, s in (("full", sf), ("trunc", st)):
    res["leader_gap"][cond] = {"leader": lead[cond][0], "second": lead[cond][1], "gap": s[lead[cond][0]] - s[lead[cond][1]], "ci": ci([b["gap"][cond] for b in boots])}
res["engines"] = {}
for e in sorted(names, key=lambda e: (-abs(st[e] - sf[e]), e)):
    res["engines"][e] = {"full": sf[e], "trunc": st[e], "delta": st[e] - sf[e], "ci": ci([b["d"][e] for b in boots])}
res["ci_excludes_zero"] = [e for e, v in res["engines"].items() if v["ci"][0] > 0 or v["ci"][1] < 0]

print("engines", len(names), "queries", len(queries))
print("full order:", res["order_full"][:5], "...", res["order_full"][-3:])
print("trunc order:", res["order_trunc"][:5], "...", res["order_trunc"][-3:])
for k in ("tau_b", "spearman", "mad"):
    print(f"{k} {res[k]:.3f} ci ({res[k + '_ci'][0]:.3f}, {res[k + '_ci'][1]:.3f})")
for e in res["ci_excludes_zero"]:
    v = res["engines"][e]
    print(f"  {e:18s} full {v['full']:.3f} trunc {v['trunc']:.3f} d {v['delta']:+.3f} ci [{v['ci'][0]:+.3f},{v['ci'][1]:+.3f}]")
for cond, g in res["leader_gap"].items():
    print(f"{cond}: leader {g['leader']} over {g['second']} gap {g['gap']:+.3f} ci ({g['ci'][0]:+.3f}, {g['ci'][1]:+.3f})")
json.dump(res, open(out_path, "w"), indent=1)
