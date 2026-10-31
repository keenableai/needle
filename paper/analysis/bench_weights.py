import collections
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import ACCOUNT_SIDE_FAILURES, BENCHES, FAMILIES, NAMES, ULT, load, overall, shares, window

hist, out = sys.argv[1], sys.argv[2]
rows = load(hist)
w, end = window(rows, 30)
engines_all = sorted({r["engine"] for r in w} - {ULT})
keep0 = [e for e in engines_all if e not in FAMILIES or e == "brave-llmcontext"]
full_ts = set()
for b, m in BENCHES:
    by_ts = collections.defaultdict(set)
    for r in w:
        if r["bench"] == b and ((r.get(m) is not None and r["num_scored"]) or r["engine"] in ACCOUNT_SIDE_FAILURES):
            by_ts[r["ts"]].add(r["engine"])
    full_ts |= {ts for ts, es in by_ts.items() if all(e in es for e in keep0)}
w = [r for r in w if r["ts"] in full_ts]
sh, _ = shares(w, keep0)
base = {e: overall(sh, e) for e in keep0}
order = sorted(keep0, key=lambda e: -base[e])


def tau_b(a, b):
    c = d = 0
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            x = (a.index(a[i]) - a.index(a[j])) * (b.index(a[i]) - b.index(a[j]))
            c += x > 0
            d += x < 0
    return (c - d) / (c + d)


print("Keenable-Exa gap by bench (share points, divided by 5 for the overall contribution):")
gap = {b: (sh["keenable"][b][1] - sh["exa"][b][1]) * 100 for b, _ in BENCHES}
for b, _ in BENCHES:
    print(f"  {b:13s} {gap[b]:+6.1f}  -> overall {gap[b] / 5:+5.2f}")
print("  total overall gap %+.1f" % ((base["keenable"] - base["exa"]) * 100))
res = {"gap_keenable_exa_by_bench": gap, "overall_gap": (base["keenable"] - base["exa"]) * 100, "drop_one": {}}
for b, _ in BENCHES:
    others = [bb for bb, _ in BENCHES if bb != b]
    o = {e: sum(sh[e][bb][1] for bb in others) / len(others) for e in keep0}
    oo = sorted(keep0, key=lambda e: -o[e])
    res["drop_one"][b] = {"order": oo, "tau_b": tau_b(order, oo), "top": oo[:3], "shares": o}
    print(f"drop {b:13s}: tau_b {tau_b(order, oo):.3f} top3 {[NAMES[e] for e in oo[:3]]} leader gap {100*(o[oo[0]]-o[oo[1]]):+.1f}")
json.dump(res, open(out, "w"), indent=1)
