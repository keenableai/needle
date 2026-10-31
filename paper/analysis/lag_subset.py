import collections
import glob
import json
import os
import random
import sys
from datetime import datetime

site = sys.argv[1]
LO, HI = "2026-10-17", "2026-10-30"
KEEP = "keenable exa google bing brave brave-llmcontext parallel perplexity tavily linkup tinyfish octen ceramic you firecrawl kagi jina context deepseek claude-search chatgpt-search".split()
ACCOUNT_SIDE = {"perplexity", "exa", "kagi", "parallel", "claude-search"}
rng = random.Random(3)


def ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ")


rows = []
run_span = {}
for d in sorted(glob.glob(os.path.join(site, "hfnews", "*"))):
    name = os.path.basename(d)
    if not (LO <= name[:10] < HI) or not os.path.exists(os.path.join(d, "ndcg.json")):
        continue
    rep = json.load(open(os.path.join(d, "ndcg.json")))
    pqs = {}
    for e in KEEP:
        if e in rep["engines"]:
            p = os.path.join(d, rep["engines"][e].get("per_query_path", ""))
            if os.path.isfile(p):
                pqs[e] = json.load(open(p))["per_query"]
    if len(pqs) < 19:
        continue
    n = len(next(iter(pqs.values())))
    times_all = []
    for qi in range(n):
        recs = {e: pqs[e][qi] for e in pqs if pqs[e][qi].get("queried_at")}
        if len(recs) < 10:
            continue
        t = {e: ts(r["queried_at"]) for e, r in recs.items()}
        t0 = min(t.values())
        spread = (max(t.values()) - t0).total_seconds()
        for e, r in recs.items():
            if r.get("search_error") and e in ACCOUNT_SIDE:
                continue
            rows.append({"run": name, "q": qi, "e": e, "score": float(r.get("score") or 0.0), "lag": (t[e] - t0).total_seconds(), "spread": spread})
        times_all.extend(t.values())
    run_span[name] = (max(times_all) - min(times_all)).total_seconds() if times_all else None

engines = sorted({r["e"] for r in rows})
print("runs", len(run_span), "rows", len(rows), "queries", len({(r["run"], r["q"]) for r in rows}))


def means(sel):
    acc = collections.defaultdict(list)
    for r in sel:
        acc[r["e"]].append(r["score"])
    return {e: sum(v) / len(v) for e, v in acc.items() if v}, {e: len(v) for e, v in acc.items()}


def tau_b(a, b):
    keys = [k for k in a if k in b]
    c = d = 0
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            x = (a[keys[i]] - a[keys[j]]) * (b[keys[i]] - b[keys[j]])
            c += x > 0
            d += x < 0
    return (c - d) / (c + d) if c + d else float("nan")


def rank_corr(x, y):
    def rk(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for pos, i in enumerate(s):
            r[i] = pos
        return r
    rx, ry = rk(x), rk(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx) ** 0.5
    vy = sum((b - my) ** 2 for b in ry) ** 0.5
    return cov / (vx * vy) if vx and vy else float("nan")


full, nfull = means(rows)
lag_mean = {e: sum(r["lag"] for r in rows if r["e"] == e) / nfull[e] for e in engines}
print("engine mean lag (min) vs mean nDCG, Spearman across engines: %.2f" % rank_corr([lag_mean[e] for e in engines], [full[e] for e in engines]))
print("mean lag by engine (min):", {e: round(lag_mean[e] / 60, 1) for e in sorted(engines, key=lag_mean.get)})

subsets = {
    "lag <= 5 min": [r for r in rows if r["lag"] <= 300],
    "lag <= 10 min": [r for r in rows if r["lag"] <= 600],
    "queries with spread <= 10 min (all engines)": [r for r in rows if r["spread"] <= 600],
    "runs with span <= 15 min": [r for r in rows if run_span[r["run"]] is not None and run_span[r["run"]] <= 900],
}
out = {"runs": len(run_span), "rows": len(rows), "lag_mean_min": {e: lag_mean[e] / 60 for e in engines}, "full": full, "n_full": nfull, "subsets": {}}
for name, sel in subsets.items():
    m, n = means(sel)
    common = [e for e in engines if e in m and n[e] >= 30]
    tb = tau_b({e: full[e] for e in common}, {e: m[e] for e in common})
    qs = {(r["run"], r["q"]) for r in sel}
    clusters = collections.defaultdict(list)
    for r in sel:
        clusters[(r["run"], r["q"])].append(r)
    cl = list(clusters.values())
    diffs = collections.defaultdict(list)
    for _ in range(500):
        samp = [r for _k in range(len(cl)) for r in cl[rng.randrange(len(cl))]]
        mb, _ = means(samp)
        for e in common:
            if e in mb:
                diffs[e].append(mb[e] - full[e])
    ci = {}
    for e in common:
        v = sorted(diffs[e])
        ci[e] = (v[int(.025 * len(v))], v[int(.975 * len(v))])
    print(f"== {name}: rows {len(sel)} queries {len(qs)} runs {len({r['run'] for r in sel})} engines {len(common)} tau_b vs full {tb:.3f}")
    moved = sorted(common, key=lambda e: -abs(m[e] - full[e]))[:6]
    for e in moved:
        print(f"   {e:17s} n {n[e]:4d} full {full[e]:.3f} subset {m[e]:.3f} diff {m[e]-full[e]:+.3f} ci [{ci[e][0]:+.3f},{ci[e][1]:+.3f}]")
    out["subsets"][name] = {"rows": len(sel), "queries": len(qs), "runs": len({r['run'] for r in sel}), "tau_b": tb, "means": m, "n": n, "ci_diff": ci}

within = collections.defaultdict(list)
for r in rows:
    within[r["e"]].append((r["lag"], r["score"]))
wc = {e: rank_corr([a for a, _ in v], [b for _, b in v]) for e, v in within.items() if len(v) >= 100}
print("within-engine Spearman(lag, nDCG), median %.3f, range %.3f..%.3f" % (sorted(wc.values())[len(wc) // 2], min(wc.values()), max(wc.values())))
out["within_engine_spearman"] = wc
json.dump(out, open(sys.argv[2], "w"), indent=1)
