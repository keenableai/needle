import collections
import copy
import glob
import json
import os
import sys

sys.path.insert(0, sys.argv[2])
from common import BENCHES, FAMILIES, ULT, account_errors, load, overall, shares, window  # noqa: E402

REPORTS = {"news": ("hfnews", "ndcg.json"), "agentic_rare": ("hfrare", "agentic_rare.json")}
rows = load(sys.argv[1])
runs = {(b, os.path.basename(d)[:13] + ":" + os.path.basename(d)[13:15] + "Z"): d for b, (folder, _) in REPORTS.items() for d in glob.glob(os.path.join(sys.argv[3], folder, "*"))}
w, end = window(rows, 30)
engines = sorted({r["engine"] for r in w} - {ULT})
keep = [e for e in engines if e not in FAMILIES or e == "brave-llmcontext"]
full_ts = set()
for b, m in BENCHES:
    by_ts = collections.defaultdict(set)
    for r in w:
        if r["bench"] == b and ((r.get(m) is not None and r["num_scored"]) or account_errors(r)):
            by_ts[r["ts"]].add(r["engine"])
    full_ts |= {ts for ts, es in by_ts.items() if all(e in es for e in keep)}
wc = [r for r in w if r["ts"] in full_ts]
print("common-support window", min(full_ts), "to", max(full_ts))


def tau_b(a, b):
    n = len(a); c = d = ta = tb = 0
    for i in range(n):
        for j in range(i + 1, n):
            x, y = a[i] - a[j], b[i] - b[j]
            if x == 0 and y == 0:
                continue
            if x == 0:
                ta += 1
            elif y == 0:
                tb += 1
            elif x * y > 0:
                c += 1
            else:
                d += 1
    return (c - d) / (((c + d + ta) * (c + d + tb)) ** 0.5)


sh, ult = shares(wc, engines)
base = {e: overall(sh, e) for e in keep}
names = sorted(base, key=lambda e: -base[e])
sh30, _ = shares(w, engines)
ov30 = {e: overall(sh30, e) for e in names}
print("30-day unequal support vs Table 1: tau_b %.3f max|d| %.1f" % (tau_b([base[e] for e in names], [ov30[e] for e in names]), max(abs(ov30[e] - base[e]) for e in names) * 100))
r30 = sorted(names, key=lambda e: -ov30[e])
for e in names:
    if abs(ov30[e] - base[e]) > 0.02:
        print(f"   {e:18s} common {base[e]*100:.1f} (rank {names.index(e)+1}) -> 30-day {ov30[e]*100:.1f} (rank {r30.index(e)+1})")


def answered(r):
    if r["bench"] not in REPORTS:
        return r["num_queries"] - r["search_errors"]
    d = runs[(r["bench"], r["ts"])]
    rep = json.load(open(os.path.join(d, REPORTS[r["bench"]][1])))
    pqs = [json.load(open(os.path.join(d, rep["engines"][e]["per_query_path"])))["per_query"] for e in (r["engine"], ULT)]
    return sum(q["search_error"] is None and u["ndcg"] is not None for q, u in zip(*pqs, strict=True))


def excluded(rs):
    out = []
    for r in rs:
        r = copy.copy(r)
        m = dict(BENCHES)[r["bench"]]
        if r["search_errors"] and r["engine"] != ULT and r.get(m) is not None:
            good = answered(r)
            if good <= 0:
                continue
            r[m] = r[m] * r["num_scored"] / good
            r["num_scored"] = good
        out.append(r)
    return out


she, _ = shares(excluded(wc), engines)
ove = {e: overall(she, e) for e in names}
re_ = sorted(names, key=lambda e: -ove[e])
print("excluded policy vs Table 1: tau_b %.3f" % tau_b([base[e] for e in names], [ove[e] for e in names]))
for e in names:
    if abs(ove[e] - base[e]) > 0.02:
        print(f"   {e:18s} {base[e]*100:.1f} -> {ove[e]*100:.1f} rank {names.index(e)+1}->{re_.index(e)+1}")
print("others move at most %.1f" % (max(abs(ove[e] - base[e]) for e in names if abs(ove[e] - base[e]) <= 0.02) * 100))
absm = {e: sum(sh[e][b][0] for b, _ in BENCHES) / 5 for e in names}
print("share vs mean-absolute tau_b %.3f" % tau_b([base[e] for e in names], [absm[e] for e in names]))
ra = sorted(names, key=lambda e: -absm[e])
print("moves", {e: ra.index(e) - names.index(e) for e in names if ra.index(e) != names.index(e)})
print("range %.1f-%.1f" % (min(base.values()) * 100, max(base.values()) * 100))
