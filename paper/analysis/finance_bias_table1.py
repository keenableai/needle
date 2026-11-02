import collections
import json
import os
import sys
from unittest.mock import patch

from common import load, order_tau, overall, shares
from finance_runs import finance_run

from needle.finance import canon
from needle.finance.models import FIELD_SPECS
from needle.finance.score import result_answers
from needle.shared.search import SearchResult

here = os.path.dirname(os.path.abspath(__file__))
audit = os.path.join(here, "audit")
site, no_reading_path, hist = sys.argv[1], sys.argv[2], sys.argv[3]
BAND = 0.02
pairs = json.load(open(os.path.join(audit, "adjacent_pairs.json")))
TABLE_RUNS, ENGINES = set(pairs["runs"]), pairs["order"]
MONEY = {f for f, s in FIELD_SPECS.items() if s.field_type == "money"}
HEAD = {f for f, s in FIELD_SPECS.items() if s.field_type == "numeric_band"}
precision = json.load(open(os.path.join(audit, "precision_audit.json")))
weighted, banded = precision["weighted_matcher"], precision["strata"]["money_banded"]
reading = {tuple(k.rsplit(" ", 1)): n for k, n in json.load(open(os.path.join(audit, "table_reading", "recheck.json"))).items()}
misses = {tuple(k.split()[:2]): n for k, n in json.load(open(os.path.join(audit, "misses", "recover.json"))).items()}
reading_hits = sum(n for (kind, _), n in reading.items() if kind == "table")
reading_confirmed = reading.get(("table", "yes"), 0)
current_misses = sum(n for (_, status), n in misses.items() if status == "miss")
misses_with_answer = sum(n for (verdict, status), n in misses.items() if verdict == "present" and status == "miss")
FP_MONEY_EXACT, FP_MONEY_READING = 1 - weighted["money"], 1 - reading_confirmed / reading_hits
FP_HEAD, FP_OTHER = 1 - weighted["headcount"], 1 - weighted["other"]
FN_MONEY, FN_MONEY_BAND = misses_with_answer / current_misses, banded["yes"] / banded["n"]


def band_match(query, results):
    with patch.multiple(canon, MONEY_REL_TOL=BAND, _match_table_figure=lambda *a, **k: False):
        return any(result_answers(query, SearchResult(url=r["url"], title=r["title"], snippet=r["snippet"]), snippet_chars=0)
                   for r in results)


window = [r for r in load(hist) if r["ts"] in TABLE_RUNS]
sh, ult = shares(window, ENGINES)
runs = sorted({r["ts"] for r in window if r["bench"] == "finance"})
no_reading = {e: v["finance_recall_no_reading"] for e, v in json.load(open(no_reading_path))["engines"].items()}
strata = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
for ts in runs:
    rep, queries = finance_run(os.path.join(site, "hf", ts.replace(":", "")))
    for e in ENGINES:
        for pq in rep["engines"][e]["per_query"]:
            if pq["score"] is None:
                continue
            f = pq["field"]
            st = strata[e]["money" if f in MONEY else "head" if f in HEAD else "other"]
            hit = pq["hit_rank"] is not None
            st["n"] += 1
            st["hit"] += hit
            if f in MONEY and pq["results"]:
                st["answered"] += 1
                st["band"] += not hit and band_match(queries[pq["query"]], pq["results"])
money_misses = sum(strata[e]["money"]["answered"] - strata[e]["money"]["hit"] for e in ENGINES)
band_misses = sum(strata[e]["money"]["band"] for e in ENGINES)
pooled = {k: sum(strata[e][k]["n"] for e in ENGINES) for k in ("money", "head", "other")}
prevalence = {k: n / sum(pooled.values()) for k, n in pooled.items()}
print(len(runs), "finance runs,", len(ENGINES), "configurations; field shares", "  ".join(f"{k} {v:.3f}" for k, v in prevalence.items()))
print(f"rates: FP money exact {FP_MONEY_EXACT:.4f}, FP table reading {FP_MONEY_READING:.4f} ({reading_hits - reading_confirmed}/{reading_hits}), "
      f"FP headcount {FP_HEAD:.4f}, FP other {FP_OTHER:.4f}, FN money {FN_MONEY:.4f} ({misses_with_answer}/{current_misses}), "
      f"FN money 0.1-{100 * BAND:g}% {FN_MONEY_BAND:.4f} ({banded['yes']}/{banded['n']})")
print(f"money misses with results {money_misses}, of them with a result 0.1-{100 * BAND:g}% from the gold {band_misses} ({band_misses / money_misses:.3f})")

rows = []
for e in sorted(ENGINES, key=lambda e: -sh[e]["finance"][0]):
    R = sh[e]["finance"][0]
    m, h, o = (strata[e][k] for k in ("money", "head", "other"))
    n = m["n"] + h["n"] + o["n"]
    p_m, p_h, p_o = m["n"] / n, h["n"] / n, o["n"] / n
    r_m, r_h, r_o = m["hit"] / m["n"], h["hit"] / h["n"], o["hit"] / o["n"]
    x_m = min(max(0.0, R - no_reading[e]) / p_m, r_m)
    a_m, b_m = m["answered"] / m["n"], m["band"] / m["n"]
    fp = p_m * (FP_MONEY_EXACT * (r_m - x_m) + FP_MONEY_READING * x_m) + p_h * FP_HEAD * r_h + p_o * FP_OTHER * r_o
    fn = p_m * (FN_MONEY_BAND * b_m + FN_MONEY * (a_m - r_m - b_m))
    rows.append({"engine": e, "reported": R, "strata_recall": p_m * r_m + p_h * r_h + p_o * r_o, "corrected": R + fn - fp,
                 "no_reading": no_reading[e], "money_recall": r_m, "reading_share": x_m, "head_recall": r_h,
                 "other_recall": r_o, "fp": fp, "fn": fn, "net": fn - fp, "money_prevalence": p_m,
                 "head_prevalence": p_h, "other_prevalence": p_o, "money_answered": a_m, "money_band_miss": b_m,
                 "n_per_query": n})
    print(f"{e:17s} R {R:.3f} money r {r_m:.3f} reading {x_m:.3f} head {r_h:.2f} other {r_o:.2f} answered {a_m:.3f} band miss {b_m:.3f} | "
          f"FP {fp:.3f} FN {fn:.3f} net {fn - fp:+.3f}  (p_money {p_m:.3f} p_head {p_h:.3f}, n {n})")

cor = {x["engine"]: x["corrected"] for x in rows}
order_rep = [x["engine"] for x in rows]
order_cor = sorted(order_rep, key=lambda e: -cor[e])
adjacent = [(a, b) for a, b in zip(order_rep, order_rep[1:], strict=False) if cor[a] < cor[b]]
discordant = sum(1 for i, a in enumerate(order_rep) for b in order_rep[i + 1:] if cor[a] < cor[b])
sh_cor = {e: {**sh[e], "finance": (cor[e], cor[e] / ult["finance"])} for e in ENGINES}
overall_rep = {e: overall(sh, e) for e in ENGINES}
overall_cor = {e: overall(sh_cor, e) for e in ENGINES}
overall_order_rep = sorted(ENGINES, key=lambda e: -overall_rep[e])
overall_order_cor = sorted(ENGINES, key=lambda e: -overall_cor[e])
summary = {
    "runs": runs,
    "money_band": BAND,
    "prevalence": prevalence,
    "rates": {"fp_money_exact": FP_MONEY_EXACT, "fp_money_reading": FP_MONEY_READING, "fp_head": FP_HEAD,
              "fp_other": FP_OTHER, "fn_money": FN_MONEY, "fn_money_band": FN_MONEY_BAND},
    "table_reading_hits": reading_hits,
    "table_reading_confirmed": reading_confirmed,
    "current_misses": current_misses,
    "misses_with_answer": misses_with_answer,
    "money_misses_with_results": money_misses,
    "money_band_misses": band_misses,
    "strata_recall_max_abs_diff": max(abs(x["reported"] - x["strata_recall"]) for x in rows),
    "net_min": min(x["net"] for x in rows),
    "net_max": max(x["net"] for x in rows),
    "reported_spread": max(x["reported"] for x in rows) - min(x["reported"] for x in rows),
    "corrected_spread": max(cor.values()) - min(cor.values()),
    "adjacent_swaps": adjacent,
    "positions_changed": sum(1 for a, b in zip(order_rep, order_cor, strict=True) if a != b),
    "discordant_pairs": discordant,
    "corrected_order": order_cor,
    "finance_ceiling": ult["finance"],
    "overall_order": overall_order_rep,
    "overall_order_corrected": overall_order_cor,
    "overall_tau_b": order_tau(overall_order_rep, overall_order_cor),
    "overall_lead_corrected": overall_cor[overall_order_cor[0]] - overall_cor[overall_order_cor[1]],
}
print(f"strata recall vs dashboard recall: max abs diff {summary['strata_recall_max_abs_diff']:.2e}")
print(f"net range {summary['net_min']:+.3f} to {summary['net_max']:+.3f}; reported spread {summary['reported_spread']:.3f}, corrected {summary['corrected_spread']:.3f}")
print("adjacent swaps:", adjacent, "positions changed:", summary["positions_changed"], "discordant pairs:", discordant)
print(f"overall order with corrected finance share (ceiling {ult['finance']:.3f}): tau_b {summary['overall_tau_b']:.3f}; "
      f"leader {overall_order_cor[0]} by {100 * summary['overall_lead_corrected']:.1f} points over {overall_order_cor[1]}")
for i, e in enumerate(overall_order_cor):
    print(f"  {i + 1:2d} {e:17s} overall {100 * overall_rep[e]:.1f} -> {100 * overall_cor[e]:.1f}  rank {overall_order_rep.index(e) + 1} -> {i + 1}")
json.dump({**summary, "engines": [x | {"overall": overall_rep[x["engine"]], "overall_corrected": overall_cor[x["engine"]]} for x in rows]},
          open(os.path.join(audit, "finance_bias_table1.json"), "w"), indent=1)
