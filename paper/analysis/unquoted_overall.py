import json

from common import order_tau

here = __file__.rsplit("/", 1)[0] + "/audit/"
bw = json.load(open(here + "bench_weights.json"))
rq = json.load(open(here + "rare_quoted.json"))
drop = bw["drop_one"]["agentic_rare"]["shares"]
unq = rq["unquoted"]["shares"]
engines = [e for e in drop if unq.get(e) is not None]
overall = {e: (drop[e] * 4 + unq[e]) / 5 for e in engines}
base_order = json.load(open(here + "adjacent_pairs.json"))["order"]
order = sorted(engines, key=lambda e: -overall[e])
tau = order_tau(base_order, order)

print(f"unquoted-rare overall: tau_b vs Table 1 {tau:.3f}")
print("top5", [(e, round(100 * overall[e], 1)) for e in order[:5]], "bottom3", order[-3:])
print(f"Keenable-Exa gap {100 * (overall['keenable'] - overall['exa']):+.1f}")
json.dump({"overall": overall, "order": order, "tau_b": tau}, open(here + "unquoted_overall.json", "w"), indent=1)
