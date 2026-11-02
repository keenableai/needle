import collections
import glob
import json
import os
import random
import sys

from common import KEEP, ci, load, order_tau, pct
from query_values import BENCHES, load_run, run_values

site, pairs_json, hist, out_json = sys.argv[1:5]
pairs_ref = json.load(open(pairs_json))
table_runs = set(pairs_ref["runs"])
hist_rows = {(r["bench"], r["ts"], r["engine"]): r for r in load(hist) if r["ts"] in table_runs}
ENGINES = KEEP + ["ultimate"]
rng = random.Random(17)


def paper_key(d):
    out = {}
    p = os.path.join(d, "scholar.jsonl")
    if os.path.exists(p):
        for line in open(p):
            if line.strip():
                g = json.loads(line)
                o = g["query_origin"]
                o = json.loads(o) if isinstance(o, str) else o
                out[g["query_text"]] = o.get("provenance", {}).get("url") or o.get("provenance", {}).get("title") or g["query_text"]
    return out


check = collections.Counter()
mismatch = []
runs_used = collections.Counter()
query_runs = collections.Counter()
clusters_by_bench = {}
for bench, (folder, report, m) in BENCHES.items():
    clusters = collections.defaultdict(lambda: {e: [0.0, 0] for e in ENGINES})
    for d in sorted(glob.glob(os.path.join(site, folder, "*"))):
        name = os.path.basename(d)
        ts = name[:13] + ":" + name[13:15] + "Z"
        if ts not in table_runs or not os.path.exists(os.path.join(d, report)):
            continue
        pqs = load_run(d, bench)
        if pqs is None:
            check[f"{bench}: run skipped, per-query files missing"] += 1
            continue
        vals = {e: [q["ndcg"] for q in pqs[e]] for e in ENGINES} if m == "ndcg" else run_values(bench, pqs)
        for e in ENGINES:
            xs = [x for x in vals[e] if x is not None]
            mean = sum(xs) / len(xs) if xs else None
            row = hist_rows.get((bench, ts, e))
            ok = row is not None and len(xs) == row["num_scored"] and abs((mean or 0) - (row.get(m) or 0)) < 1e-9
            check[f"{bench}: row reproduced {ok}"] += 1
            if not ok:
                mismatch.append((bench, ts, e, len(xs), mean, row and row["num_scored"], row and row.get(m)))
        pk = paper_key(d) if bench == "scholar" else {}
        for qi, q in enumerate(pqs["ultimate"]):
            c = clusters[pk.get(q["query"], q["query"])]
            for e in ENGINES:
                if vals[e][qi] is not None:
                    c[e][0] += vals[e][qi]
                    c[e][1] += 1
        runs_used[bench] += 1
        query_runs[bench] += len(pqs["ultimate"])
    cl = list(clusters.values())
    clusters_by_bench[bench] = {"n": len(cl), "sum": {e: [c[e][0] for c in cl] for e in ENGINES}, "cnt": {e: [c[e][1] for c in cl] for e in ENGINES}}
    print(bench, "runs", runs_used[bench], "clusters", len(cl), "query-runs", query_runs[bench], flush=True)
for k, v in sorted(check.items()):
    print(k, v)
for x in mismatch[:20]:
    print("  row mismatch", x)


def overall(sel):
    acc = collections.defaultdict(list)
    for bench, cb in clusters_by_bench.items():
        tot = {e: (sum(map(cb["sum"][e].__getitem__, sel[bench])), sum(map(cb["cnt"][e].__getitem__, sel[bench]))) for e in ENGINES}
        if not tot["ultimate"][0] or not tot["ultimate"][1]:
            continue
        u = tot["ultimate"][0] / tot["ultimate"][1]
        for e in KEEP:
            if tot[e][1]:
                acc[e].append(tot[e][0] / tot[e][1] / u)
    return {e: sum(v) / len(v) for e, v in acc.items() if len(v) == len(clusters_by_bench)}


base = overall({b: range(cb["n"]) for b, cb in clusters_by_bench.items()})
order = sorted(base, key=lambda e: -base[e])
table1 = pairs_ref["base"]
dev = {e: 100 * (base[e] - table1[e]) for e in order}
worst = max(dev, key=lambda e: abs(dev[e]))
print("runs used", dict(runs_used), "of", {b: len({t for (bb, t, _) in hist_rows if bb == b}) for b in BENCHES})
print(f"max |cluster base - Table 1| {abs(dev[worst]):.3f} points ({worst}); order tau_b vs Table 1 {order_tau(pairs_ref['order'], order):.3f}")

N = 1000
samp = collections.defaultdict(list)
for _ in range(N):
    o = overall({b: [rng.randrange(cb["n"]) for _ in range(cb["n"])] for b, cb in clusters_by_bench.items()})
    for e in order:
        samp[e].append(o.get(e, float("nan")))


Z = 3.683
pairs = {}
sep_pt = sep_bf = 0
ratios = []
for i, a in enumerate(order):
    for b in order[i + 1:]:
        d = [x - y for x, y in zip(samp[a], samp[b], strict=True) if x == x and y == y]
        lo, hi = ci(d)
        mu = sum(d) / len(d)
        sd = (sum((x - mu) ** 2 for x in d) / (len(d) - 1)) ** 0.5
        diff = base[a] - base[b]
        pt, bf = lo > 0, diff - Z * sd > 0
        sep_pt += pt
        sep_bf += bf
        run = pairs_ref["all_pairs"].get(f"{a}|{b}") or pairs_ref["all_pairs"][f"{b}|{a}"]
        ratios.append((hi - lo) / (run["hi"] - run["lo"]))
        pairs[f"{a}|{b}"] = {"diff": diff, "lo": lo, "hi": hi, "sep": pt, "sep_bonferroni": bf}
adj = sum(pairs[f"{a}|{b}"]["sep"] for a, b in zip(order, order[1:], strict=False))
fully = [e for e in order if all(pairs.get(f"{e}|{f}", pairs.get(f"{f}|{e}"))["sep_bonferroni"] for f in order if f != e)]
lead = pairs.get("keenable|exa") or pairs.get("exa|keenable")
narrower = sum(r < 1 for r in ratios)
print(f"cluster bootstrap: pointwise separated {sep_pt}/{len(pairs)}, Bonferroni {sep_bf}/{len(pairs)}, adjacent {adj}/{len(order) - 1}; fully separated {fully}")
print(f"keenable-exa diff {lead['diff']:.3f} ci [{lead['lo']:.3f}, {lead['hi']:.3f}]")
print(f"interval width vs run resampling: median ratio {pct(ratios, .5):.2f}, narrower for {narrower}/{len(ratios)} pairs")
json.dump({"scorer": "dashboard rows per query: stored nDCG on news and rare; finance money rematched by scripts/backfill_scores.rematch_money; on finance, scholar and legal account-side failures (needle.shared.search.errors.account_side) excluded and service-side failures zero",
           "runs": dict(runs_used), "query_runs": dict(query_runs), "clusters": {b: cb["n"] for b, cb in clusters_by_bench.items()},
           "row_check": dict(check), "row_mismatches": mismatch, "table1": table1, "base": base, "base_minus_table1_points": dev,
           "order": order, "tau_b_table1_order": order_tau(pairs_ref["order"], order), "pairs": pairs, "pointwise": sep_pt, "bonferroni": sep_bf,
           "adjacent": adj, "fully": fully, "width_ratio_median": pct(ratios, .5), "narrower": narrower}, open(out_json, "w"), indent=1)
