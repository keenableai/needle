import json

from common import order_tau

here = __file__.rsplit("/", 1)[0] + "/audit/"
pairs = json.load(open(here + "adjacent_pairs.json"))
base, order = pairs["base"], pairs["order"]
out = {}
for name, path, alt in (("no_table_reading", "no_table_reading.json", "finance_share_no_reading"),
                        ("reading_correction", "fresh/reading_correction.json", "finance_share_corrected")):
    engines = json.load(open(here + path))["engines"]
    shifted = {e: base[e] - (engines[e]["finance_share"] - engines[e][alt]) / 5 for e in order}
    new_order = sorted(order, key=lambda e: -shifted[e])
    fixed = next((i for i, (a, b) in enumerate(zip(order, new_order, strict=True)) if a != b), len(order))
    out[name] = {"overall": shifted, "order": new_order, "overall_tau_b": order_tau(order, new_order), "top_ranks_fixed": fixed,
                 "lead": shifted[new_order[0]] - shifted[new_order[1]]}
    print(f"{name}: overall tau_b {out[name]['overall_tau_b']:.3f}; ranks 1-{fixed} fixed; order {new_order}")
json.dump(out, open(here + "one_policy_finance_checks.json", "w"), indent=1)
