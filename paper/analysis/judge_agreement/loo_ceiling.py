import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

from needle.shared.metrics import normalize_url

hf_dir, out_json = Path(sys.argv[1]), sys.argv[2]
GAIN = {4: 1.0, 3: 0.667, 2: 0.117, 1: 0.0, 0: 0.0}
SITE_RE = re.compile(r"\bsite:")
K = 5
SKIP = {"ultimate"}


def dcg(ratings):
    return sum(GAIN.get(r, 0.0) / math.log2(i + 2) for i, r in enumerate(ratings[:K]))


def idcg_from_pool(best):
    ordered = sorted(best.values(), reverse=True)[:K]
    return dcg(ordered)


runs = sorted(p for p in hf_dir.iterdir() if p.is_dir() and (p / "ndcg.json").exists())
sum_full = defaultdict(float)
sum_loo = defaultdict(float)
n_full = defaultdict(int)
n_loo = defaultdict(int)
snip_len = defaultdict(list)
exceed = defaultdict(int)
n_queries = 0
for run in runs:
    rep = json.load(open(run / "ndcg.json"))
    engines = {}
    for name, e in rep["engines"].items():
        if name in SKIP or "per_query_path" not in name and "per_query_path" not in e:
            continue
        p = run / e["per_query_path"]
        if not p.exists():
            continue
        engines[name] = {pq["query"]: pq for pq in json.load(open(p))["per_query"]}
    queries = set()
    for pqs in engines.values():
        queries |= set(pqs)
    for q in queries:
        contrib = {}
        for name, pqs in engines.items():
            pq = pqs.get(q)
            if pq is None or pq["search_error"] is not None or pq.get("judge_errors"):
                continue
            best = {}
            for r in pq["results"]:
                if r.get("rating") is None:
                    continue
                key = normalize_url(r["url"])
                best[key] = max(best.get(key, 0), r["rating"])
            contrib[name] = (best, dcg(pq["penalized_ratings"]))
            for r in pq["results"]:
                snip_len[name].append(len(r.get("snippet") or ""))
        pool = {}
        for best, _ in contrib.values():
            for u, r in best.items():
                pool[u] = max(pool.get(u, 0), r)
        idcg = idcg_from_pool(pool)
        if idcg <= 0:
            continue
        n_queries += 1
        for name, (best, d) in contrib.items():
            sum_full[name] += d / idcg
            n_full[name] += 1
            pool_wo = {}
            for other, (b2, _) in contrib.items():
                if other == name:
                    continue
                for u, r in b2.items():
                    pool_wo[u] = max(pool_wo.get(u, 0), r)
            idcg_wo = idcg_from_pool(pool_wo)
            if idcg_wo <= 0:
                continue
            share = d / idcg_wo
            sum_loo[name] += share
            n_loo[name] += 1
            if share > 1.0:
                exceed[name] += 1

out = {}
for name in sum_full:
    full = sum_full[name] / n_full[name]
    loo = sum_loo[name] / n_loo[name] if n_loo[name] else None
    sl = sorted(snip_len[name])
    out[name] = {
        "n": n_full[name], "full": round(full, 4), "loo": round(loo, 4) if loo else None,
        "delta": round(loo - full, 4) if loo else None, "exceed_frac": round(exceed[name] / max(1, n_loo[name]), 4),
        "snippet_median": sl[len(sl) // 2] if sl else None,
    }
print("runs", len(runs), "queries with idcg>0", n_queries)
rank_full = sorted(out, key=lambda n: -out[n]["full"])
rank_loo = sorted(out, key=lambda n: -(out[n]["loo"] or 0))
for name in rank_full:
    o = out[name]
    print(f"{name:20s} n={o['n']:5d} full={o['full']:.3f} loo={o['loo']:.3f} d={o['delta']:+.3f} >1:{o['exceed_frac']:.3f} snip={o['snippet_median']}")


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


names = list(out)
print("tau_b full vs loo", round(tau_b([out[n]["full"] for n in names], [out[n]["loo"] for n in names]), 3))
print("order full:", rank_full)
print("order loo: ", rank_loo)


def spearman(a, b):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for pos, i in enumerate(order):
            r[i] = pos
        return r
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return cov / (va * vb)


print("spearman snippet_median vs full share", round(spearman([out[n]["snippet_median"] for n in names], [out[n]["full"] for n in names]), 3))
json.dump({"runs": len(runs), "queries": n_queries, "engines": out}, open(out_json, "w"), indent=1)
