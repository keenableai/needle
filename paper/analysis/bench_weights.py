import json
import sys

from common import BENCHES, NAMES, load, order_tau, overall, shares, table_window

hist, out = sys.argv[1], sys.argv[2]
w, _, keep = table_window(load(hist))
sh, _ = shares(w, keep)
base = {e: overall(sh, e) for e in keep}
order = sorted(keep, key=lambda e: -base[e])

print("Keenable-Exa gap by bench (share points, divided by 5 for the overall contribution):")
gap = {b: (sh["keenable"][b][1] - sh["exa"][b][1]) * 100 for b, _ in BENCHES}
for b, _ in BENCHES:
    print(f"  {b:13s} {gap[b]:+6.1f}  -> overall {gap[b] / 5:+5.2f}")
print("  total overall gap %+.1f" % ((base["keenable"] - base["exa"]) * 100))
res = {"gap_keenable_exa_by_bench": gap, "overall_gap": (base["keenable"] - base["exa"]) * 100, "drop_one": {}}
for b, _ in BENCHES:
    others = [bb for bb, _ in BENCHES if bb != b]
    o = {e: sum(sh[e][bb][1] for bb in others) / len(others) for e in keep}
    oo = sorted(keep, key=lambda e: -o[e])
    res["drop_one"][b] = {"order": oo, "tau_b": order_tau(order, oo), "top": oo[:3], "shares": o}
    print(f"drop {b:13s}: tau_b {order_tau(order, oo):.3f} top3 {[NAMES[e] for e in oo[:3]]} leader gap {100*(o[oo[0]]-o[oo[1]]):+.1f}")
json.dump(res, open(out, "w"), indent=1)
