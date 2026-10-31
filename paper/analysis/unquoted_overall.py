import json
import sys

here = __file__.rsplit("/", 1)[0] + "/audit/"
bw = json.load(open(here + "bench_weights.json"))
rq = json.load(open(here + "rare_quoted.json"))
drop = bw["drop_one"]["agentic_rare"]["shares"]
unq = rq["unquoted"]["shares"]
engines = [e for e in drop if unq.get(e) is not None]
overall = {e: (drop[e] * 4 + unq[e]) / 5 for e in engines}
base_order = json.load(open(here + "adjacent_pairs.json"))["order"]
order = sorted(engines, key=lambda e: -overall[e])


def tau_b(a, b):
    c = d = 0
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            x = (a.index(a[i]) - a.index(a[j])) * (b.index(a[i]) - b.index(a[j]))
            c += x > 0
            d += x < 0
    return (c - d) / (c + d)


print("unquoted-rare overall: tau_b vs Table 1 %.3f" % tau_b(base_order, order))
print("top5", [(e, round(100 * overall[e], 1)) for e in order[:5]], "bottom3", order[-3:])
print("Keenable-Exa gap %+.1f" % (100 * (overall["keenable"] - overall["exa"])))
json.dump({"overall": overall, "order": order, "tau_b": tau_b(base_order, order)}, open(here + "unquoted_overall.json", "w"), indent=1)
