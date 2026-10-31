import collections
import glob
import json
import os
import sys

site, final_hist, v3_hist = sys.argv[1], sys.argv[2], sys.argv[3]
LO, HI = "2026-10-17", "2026-10-30"
MONEY = {"revenue", "net_income", "operating_income", "eps_diluted"}
HEAD = {"employees"}
FP_MONEY_STRICT, FP_MONEY_EXT, FN_MONEY = 1 - 130 / 140, 1 - 73 / 80, 10 / 100
FP_HEAD, FP_OTHER = 1 - 37 / 40, 1 - 58 / 59


def recall(path):
    acc = collections.defaultdict(lambda: [0.0, 0])
    for line in open(path):
        if not line.strip():
            continue
        r = json.loads(line)
        if r["bench"] != "finance" or not (LO <= r["ts"][:10] < HI) or r.get("recall") is None or not r["num_scored"]:
            continue
        acc[r["engine"]][0] += r["recall"] * r["num_scored"]
        acc[r["engine"]][1] += r["num_scored"]
    return {e: (s / n, n) for e, (s, n) in acc.items() if n}


before, after = recall(final_hist), recall(v3_hist)
strata = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
for d in sorted(glob.glob(os.path.join(site, "hf", "*"))):
    name = os.path.basename(d)
    if not (LO <= name[:10] < HI) or not os.path.exists(os.path.join(d, "recall.json")):
        continue
    rep = json.load(open(os.path.join(d, "recall.json")))
    for e, info in rep["engines"].items():
        p = os.path.join(d, info.get("per_query_path", ""))
        if not os.path.isfile(p):
            continue
        for q in json.load(open(p))["per_query"]:
            f = q.get("field") or ""
            s = "money" if f in MONEY else "head" if f in HEAD else "other"
            strata[e][s][0] += 1
            strata[e][s][1] += 1 if q.get("hit_rank") is not None else 0

rows = []
for e in sorted(after, key=lambda e: -after[e][0]):
    if e == "ultimate" or e not in before or e not in strata:
        continue
    R, N = after[e]
    st = strata[e]
    n_m, h_m_prod = st["money"]
    n_h, h_h = st["head"]
    n_o, h_o = st["other"]
    n_tot = n_m + n_h + n_o
    if not n_m or not n_tot:
        continue
    p_m, p_h, p_o = n_m / n_tot, n_h / n_tot, n_o / n_tot
    r_h, r_o = h_h / n_h if n_h else 0.0, h_o / n_o if n_o else 0.0
    r_m = (R - p_h * r_h - p_o * r_o) / p_m
    ext_total = max(0.0, after[e][0] - before[e][0])
    x_m = min(ext_total / p_m, r_m)
    fp = p_m * (FP_MONEY_STRICT * (r_m - x_m) + FP_MONEY_EXT * x_m) + p_h * FP_HEAD * r_h + p_o * FP_OTHER * r_o
    fn = p_m * FN_MONEY * (1 - r_m)
    rows.append((e, R, r_m, x_m, r_h, r_o, fp, fn, fn - fp, p_m))
    print(f"{e:17s} R {R:.3f} money r {r_m:.3f} ext {x_m:.3f} head {r_h:.2f} other {r_o:.2f} | FP {fp:.3f} FN {fn:.3f} net {fn - fp:+.3f}  (p_money {p_m:.2f})")
nets = [x[8] for x in rows]
rep_spread = max(x[1] for x in rows) - min(x[1] for x in rows)
cor_spread = max(x[1] + x[8] for x in rows) - min(x[1] + x[8] for x in rows)
print("net range %+.3f to %+.3f; reported spread %.3f, corrected %.3f" % (min(nets), max(nets), rep_spread, cor_spread))
order_rep = [x[0] for x in rows]
order_cor = [x[0] for x in sorted(rows, key=lambda x: -(x[1] + x[8]))]
swaps = sum(1 for a, b in zip(order_rep, order_cor) if a != b)
print("order unchanged:", order_rep == order_cor, "positions changed:", swaps)
json.dump([dict(zip(("engine", "reported", "money_recall", "extension_share", "head_recall", "other_recall", "fp", "fn", "net", "money_prevalence"), x)) for x in rows],
          open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit", "finance_bias.json"), "w"), indent=1)
