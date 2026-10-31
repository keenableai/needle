import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import account_side, load  # noqa: E402

here = os.path.dirname(os.path.abspath(__file__))
site, final_hist, paper_hist = sys.argv[1], sys.argv[2], sys.argv[3]
table = json.load(open(os.path.join(here, "manifest.json")))["results"]["table_results"]
TABLE_RUNS, ENGINES = set(table["runs"]), table["engines"]
MONEY = {"revenue", "net_income", "operating_income", "eps_diluted"}
HEAD = {"employees"}
FP_MONEY_STRICT, FP_MONEY_EXT, FN_MONEY = 1 - 130 / 140, 1 - 73 / 80, 10 / 100
FP_HEAD, FP_OTHER = 1 - 37 / 40, 1 - 58 / 59


def finance_rows(path):
    return [r for r in load(path) if r["bench"] == "finance" and r["ts"] in TABLE_RUNS and r["engine"] in ENGINES]


def recall(rows):
    acc = collections.defaultdict(lambda: [0.0, 0])
    for r in rows:
        if r.get("recall") is None or not r["num_scored"]:
            continue
        acc[r["engine"]][0] += r["recall"] * r["num_scored"]
        acc[r["engine"]][1] += r["num_scored"]
    return {e: (s / n, n) for e, (s, n) in acc.items() if n}


paper_rows = finance_rows(paper_hist)
runs = sorted({r["ts"] for r in paper_rows})
before, after = recall(finance_rows(final_hist)), recall(paper_rows)
strata = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0, 0]))
for ts in runs:
    d = os.path.join(site, "hf", ts.replace(":", ""))
    rep = json.load(open(os.path.join(d, "recall.json")))
    for e in ENGINES:
        for q in json.load(open(os.path.join(d, rep["engines"][e]["per_query_path"])))["per_query"]:
            if q.get("search_error") and account_side(q["search_error"]):
                continue
            f = q.get("field") or ""
            st = strata[e]["money" if f in MONEY else "head" if f in HEAD else "other"]
            st[0] += 1
            st[1] += q.get("hit_rank") is not None
            st[2] += not q.get("n_results")
print(len(runs), "finance runs,", len(ENGINES), "configurations")

rows = []
for e in sorted(ENGINES, key=lambda e: -after[e][0]):
    R, N = after[e]
    st = strata[e]
    n_m, _, u_m = st["money"]
    n_h, h_h, _ = st["head"]
    n_o, h_o, _ = st["other"]
    n_tot = n_m + n_h + n_o
    p_m, p_h, p_o = n_m / n_tot, n_h / n_tot, n_o / n_tot
    r_h, r_o = h_h / n_h if n_h else 0.0, h_o / n_o if n_o else 0.0
    r_m = (R - p_h * r_h - p_o * r_o) / p_m
    x_m = min(max(0.0, R - before[e][0]) / p_m, r_m)
    a_m = 1 - u_m / n_m
    fp = p_m * (FP_MONEY_STRICT * (r_m - x_m) + FP_MONEY_EXT * x_m) + p_h * FP_HEAD * r_h + p_o * FP_OTHER * r_o
    fn = p_m * FN_MONEY * max(0.0, a_m - r_m)
    rows.append(dict(engine=e, reported=R, money_recall=r_m, extension_share=x_m, head_recall=r_h, other_recall=r_o,
                     fp=fp, fn=fn, net=fn - fp, money_prevalence=p_m, money_answered=a_m, n_scored=N, n_per_query=n_tot))
    print(f"{e:17s} R {R:.3f} money r {r_m:.3f} ext {x_m:.3f} head {r_h:.2f} other {r_o:.2f} answered {a_m:.3f} | FP {fp:.3f} FN {fn:.3f} net {fn - fp:+.3f}  (p_money {p_m:.3f}, n {N}/{n_tot})")

cor = {x["engine"]: x["reported"] + x["net"] for x in rows}
order_rep = [x["engine"] for x in rows]
order_cor = sorted(order_rep, key=lambda e: -cor[e])
adjacent = [(a, b) for a, b in zip(order_rep, order_rep[1:]) if cor[a] < cor[b]]
discordant = sum(1 for i, a in enumerate(order_rep) for b in order_rep[i + 1:] if cor[a] < cor[b])
summary = {
    "runs": runs,
    "net_min": min(x["net"] for x in rows),
    "net_max": max(x["net"] for x in rows),
    "reported_spread": max(x["reported"] for x in rows) - min(x["reported"] for x in rows),
    "corrected_spread": max(cor.values()) - min(cor.values()),
    "adjacent_swaps": adjacent,
    "positions_changed": sum(1 for a, b in zip(order_rep, order_cor) if a != b),
    "discordant_pairs": discordant,
    "corrected_order": order_cor,
}
print("net range %+.3f to %+.3f; reported spread %.3f, corrected %.3f" % (summary["net_min"], summary["net_max"], summary["reported_spread"], summary["corrected_spread"]))
print("adjacent swaps:", adjacent, "positions changed:", summary["positions_changed"], "discordant pairs:", discordant)
json.dump({**summary, "engines": rows}, open(os.path.join(here, "audit", "finance_bias_table1.json"), "w"), indent=1)
