import json
import os
import sys

from common import NAMES, kept_engines, load, order_tau, overall, shares
from finance_runs import finance_run, prose_hit, rescore
from publish_bench import finance_rows

from needle.shared.recall import first_rank

hist, site, pairs_json, out_path = sys.argv[1:5]
table_runs = set(json.load(open(pairs_json))["runs"])
window = [r for r in load(hist) if r["ts"] in table_runs]
no_reading = [r for r in window if r["bench"] != "finance"]
for ts in sorted({r["ts"] for r in window if r["bench"] == "finance"}):
    rep, queries = finance_run(os.path.join(site, "hf", ts.replace(":", "")))
    for e in rep["engines"].values():
        for pq in e["per_query"]:
            q = queries[pq["query"]]
            if q.field_type == "money" and pq["search_error"] is None:
                pq["hit_rank"] = first_rank([prose_hit(q, r) for r in pq["results"]])
    no_reading += finance_rows(rescore(rep, "finance"), ts)
keep = kept_engines({r["engine"] for r in window})
sh0, u0 = shares(window, keep)
sh1, u1 = shares(no_reading, keep)
o0 = {e: overall(sh0, e) for e in keep if overall(sh0, e) is not None}
o1 = {e: overall(sh1, e) for e in keep if overall(sh1, e) is not None}
order0 = sorted(o0, key=lambda e: -o0[e])
order1 = sorted(o1, key=lambda e: -o1[e])
fin_order0 = sorted(keep, key=lambda e: -(sh0[e]["finance"][1] or 0))
fin_order1 = sorted(keep, key=lambda e: -(sh1[e]["finance"][1] or 0))
fin_tau, overall_tau = order_tau(fin_order0, fin_order1), order_tau(order0, order1)
print(f"finance ceiling dashboard {u0['finance']:.3f} no reading {u1['finance']:.3f}; finance order tau_b {fin_tau:.3f}; overall order tau_b {overall_tau:.3f}")
res = {"finance_ceiling": {"dashboard": u0["finance"], "no_reading": u1["finance"]}, "finance_tau_b": fin_tau, "overall_tau_b": overall_tau, "engines": {}}
for e in order0:
    d_rec = (sh0[e]["finance"][0] or 0) - (sh1[e]["finance"][0] or 0)
    res["engines"][e] = {"finance_recall": sh0[e]["finance"][0], "finance_recall_no_reading": sh1[e]["finance"][0], "finance_share": sh0[e]["finance"][1], "finance_share_no_reading": sh1[e]["finance"][1],
                         "overall": o0[e], "overall_no_reading": o1[e], "rank": order0.index(e) + 1, "rank_no_reading": order1.index(e) + 1}
    print(f"  {NAMES.get(e, e):18s} fin recall {100 * sh0[e]['finance'][0]:.1f} -> {100 * sh1[e]['finance'][0]:.1f} ({100 * d_rec:+.1f})  fin share {100 * sh0[e]['finance'][1]:.1f} -> {100 * sh1[e]['finance'][1]:.1f}  overall {100 * o0[e]:.1f} -> {100 * o1[e]:.1f}  rank {order0.index(e) + 1} -> {order1.index(e) + 1}")
json.dump(res, open(out_path, "w"), indent=1)
