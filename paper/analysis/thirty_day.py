import collections
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import ACCOUNT_SIDE_FAILURES, BENCHES, FAMILIES, NAMES, ULT, load, overall, shares, window

hist, pairs_json = sys.argv[1], sys.argv[2]
rows = load(hist)
w30, end = window(rows, 30)
table_runs = {ts for ts in json.load(open(pairs_json))["runs"]}
base_order = json.load(open(pairs_json))["order"]
keep = [e for e in sorted({r["engine"] for r in w30} - {ULT}) if e not in FAMILIES or e == "brave-llmcontext"]
sh30, _ = shares(w30, keep)
o30 = {e: overall(sh30, e) for e in keep if overall(sh30, e) is not None}
wt = [r for r in w30 if r["ts"] in table_runs]
sht, _ = shares(wt, keep)
ot = {e: overall(sht, e) for e in keep if overall(sht, e) is not None}
order30 = sorted(o30, key=lambda e: -o30[e])


def tau_b(a, b):
    c = d = 0
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            x = (a.index(a[i]) - a.index(a[j])) * (b.index(a[i]) - b.index(a[j]))
            c += x > 0
            d += x < 0
    return (c - d) / (c + d)


common = [e for e in base_order if e in order30]
print("runs 30d:", {b: len({r['ts'] for r in w30 if r['bench'] == b}) for b, _ in BENCHES}, "query-runs", sum(r["num_queries"] for r in w30 if r["engine"] == ULT))
print("tau_b table vs 30-day %.3f" % tau_b(common, [e for e in order30 if e in common]))
moves = sorted(common, key=lambda e: -abs(o30[e] - ot[e]))[:4]
for e in moves:
    print(f"  {NAMES[e]:18s} {100*ot[e]:.1f} (rank {base_order.index(e)+1}) -> {100*o30[e]:.1f} (rank {order30.index(e)+1})")
print("order30:", [NAMES[e] for e in order30]); print("top 7 and bottom 2 unchanged:", base_order[:7] == [e for e in order30 if e in common][:7], base_order[-2:] == [e for e in order30 if e in common][-2:])
