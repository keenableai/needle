import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import FAMILIES, NAMES, ULT, load, overall, shares  # noqa: E402

paper_hist, strict_hist, pairs_json, out_path = sys.argv[1:5]
table_runs = set(json.load(open(pairs_json))["runs"])
paper = [r for r in load(paper_hist) if r["ts"] in table_runs]
strict = [r for r in paper if r["bench"] != "finance"] + [r for r in load(strict_hist) if r["ts"] in table_runs and r["bench"] == "finance"]
keep = [e for e in sorted({r["engine"] for r in paper} - {ULT}) if e not in FAMILIES or e == "brave-llmcontext"]
sp, up = shares(paper, keep)
ss, us = shares(strict, keep)
op = {e: overall(sp, e) for e in keep if overall(sp, e) is not None}
os_ = {e: overall(ss, e) for e in keep if overall(ss, e) is not None}
order_p = sorted(op, key=lambda e: -op[e])
order_s = sorted(os_, key=lambda e: -os_[e])


def tau_b(a, b):
    c = d = 0
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            x = (a.index(a[i]) - a.index(a[j])) * (b.index(a[i]) - b.index(a[j]))
            c += x > 0
            d += x < 0
    return (c - d) / (c + d)


fin_p = sorted(keep, key=lambda e: -(sp[e]["finance"][1] or 0))
fin_s = sorted(keep, key=lambda e: -(ss[e]["finance"][1] or 0))
print(f"finance ceiling paper {up['finance']:.3f} strict {us['finance']:.3f}; finance order tau_b {tau_b(fin_p, fin_s):.3f}; overall order tau_b {tau_b(order_p, order_s):.3f}")
res = {"finance_ceiling": {"paper": up["finance"], "strict": us["finance"]}, "engines": {}}
for e in order_p:
    d_rec = (sp[e]["finance"][0] or 0) - (ss[e]["finance"][0] or 0)
    res["engines"][e] = {"finance_recall_paper": sp[e]["finance"][0], "finance_recall_strict": ss[e]["finance"][0], "finance_share_paper": sp[e]["finance"][1], "finance_share_strict": ss[e]["finance"][1],
                         "overall_paper": op[e], "overall_strict": os_[e], "rank_paper": order_p.index(e) + 1, "rank_strict": order_s.index(e) + 1}
    print(f"  {NAMES.get(e, e):18s} fin recall {100 * sp[e]['finance'][0]:.1f} -> {100 * ss[e]['finance'][0]:.1f} ({100 * d_rec:+.1f})  fin share {100 * sp[e]['finance'][1]:.1f} -> {100 * ss[e]['finance'][1]:.1f}  overall {100 * op[e]:.1f} -> {100 * os_[e]:.1f}  rank {order_p.index(e) + 1} -> {order_s.index(e) + 1}")
json.dump(res, open(out_path, "w"), indent=1)
