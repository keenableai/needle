import collections
import glob
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import BENCHES, FAMILIES, NAMES, ULT, load, overall, shares  # noqa: E402

hist, pairs_json, v2_glob, precision_json, out_path = sys.argv[1:6]
rows = load(hist)
table_runs = set(json.load(open(pairs_json))["runs"])
window = [r for r in rows if r["ts"] in table_runs]
keep = [e for e in sorted({r["engine"] for r in window} - {ULT}) if e not in FAMILIES or e == "brave-llmcontext"]
run_dirs = {ts.replace(":", "") for ts in table_runs}
reading = collections.Counter()
for f in glob.glob(v2_glob):
    for h in json.load(open(f))["new_hits"]:
        if h["run"] in run_dirs:
            reading[h["engine"]] += 1
prec = json.load(open(precision_json))
pooled = prec["money_reading"]["precision"]
per = {e: v for e, v in prec["money_by_engine"].items()}


def p_engine(e):
    v = per.get(e)
    return v["yes"] / v["n"] if v and v["n"] >= 20 else pooled


fin = [r for r in window if r["bench"] == "finance"]
scored = {e: sum(r["num_scored"] for r in fin if r["engine"] == e) for e in keep}
corrected = []
for r in window:
    r2 = dict(r)
    if r["bench"] == "finance" and r["engine"] in keep and scored[r["engine"]]:
        infl = reading[r["engine"]] * (1 - p_engine(r["engine"])) / scored[r["engine"]]
        r2["recall"] = max(0.0, (r["recall"] or 0.0) - infl)
    corrected.append(r2)
sh0, _ = shares(window, keep)
sh1, _ = shares(corrected, keep)
o0 = {e: overall(sh0, e) for e in keep if overall(sh0, e) is not None}
o1 = {e: overall(sh1, e) for e in keep if overall(sh1, e) is not None}
order0 = sorted(o0, key=lambda e: -o0[e])
order1 = sorted(o1, key=lambda e: -o1[e])


def tau_b(a, b):
    c = d = 0
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            x = (a.index(a[i]) - a.index(a[j])) * (b.index(a[i]) - b.index(a[j]))
            c += x > 0
            d += x < 0
    return (c - d) / (c + d)


fin_order0 = sorted(keep, key=lambda e: -(sh0[e]["finance"][1] or 0))
fin_order1 = sorted(keep, key=lambda e: -(sh1[e]["finance"][1] or 0))
res = {"pooled_precision": pooled, "engines": {}}
print(f"finance order tau_b {tau_b(fin_order0, fin_order1):.3f}; overall order tau_b {tau_b(order0, order1):.3f}")
for e in order0:
    infl = reading[e] * (1 - p_engine(e)) / scored[e] if scored[e] else 0
    res["engines"][e] = {"reading_hits": reading[e], "finance_scored": scored[e], "precision_used": p_engine(e), "finance_recall_drop": infl,
                         "finance_share": sh0[e]["finance"][1], "finance_share_corrected": sh1[e]["finance"][1], "overall": o0[e], "overall_corrected": o1[e],
                         "rank": order0.index(e) + 1, "rank_corrected": order1.index(e) + 1}
    print(f"  {NAMES.get(e, e):18s} readings {reading[e]:4d}/{scored[e]:5d} p={p_engine(e):.2f} fin recall -{100 * infl:.1f} pts  fin share {100 * sh0[e]['finance'][1]:.1f}->{100 * sh1[e]['finance'][1]:.1f}  overall {100 * o0[e]:.1f}->{100 * o1[e]:.1f}  rank {order0.index(e) + 1}->{order1.index(e) + 1}")
json.dump(res, open(out_path, "w"), indent=1)
