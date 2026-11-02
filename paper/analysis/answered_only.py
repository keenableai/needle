import copy
import glob
import json
import os
import sys

from common import BENCHES, ULT, load, overall, shares, table_window, tau_b, window

REPORTS = {"news": ("hfnews", "ndcg.json"), "agentic_rare": ("hfrare", "agentic_rare.json")}
rows = load(sys.argv[1])
runs = {(b, os.path.basename(d)[:13] + ":" + os.path.basename(d)[13:15] + "Z"): d for b, (folder, _) in REPORTS.items() for d in glob.glob(os.path.join(sys.argv[2], folder, "*"))}
w, _ = window(rows, 30)
wc, engines, keep = table_window(rows)
ts = {r["ts"] for r in wc}
print("common-support window", min(ts), "to", max(ts))

sh, _ = shares(wc, engines)
base = {e: overall(sh, e) for e in keep}
names = sorted(base, key=lambda e: -base[e])
sh30, _ = shares(w, engines)
ov30 = {e: overall(sh30, e) for e in names}
print(f"30-day unequal support vs Table 1: tau_b {tau_b([base[e] for e in names], [ov30[e] for e in names]):.3f} max|d| {max(abs(ov30[e] - base[e]) for e in names) * 100:.1f}")
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


def answered_only(rs):
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


sha, _ = shares(answered_only(wc), engines)
ova = {e: overall(sha, e) for e in names}
ra = sorted(names, key=lambda e: -ova[e])
print(f"answered-only vs Table 1: tau_b {tau_b([base[e] for e in names], [ova[e] for e in names]):.3f}")
for e in names:
    if abs(ova[e] - base[e]) > 0.02:
        print(f"   {e:18s} {base[e]*100:.1f} -> {ova[e]*100:.1f} rank {names.index(e)+1}->{ra.index(e)+1}")
print(f"others move at most {max(abs(ova[e] - base[e]) for e in names if abs(ova[e] - base[e]) <= 0.02) * 100:.1f}")
absm = {e: sum(sh[e][b][0] for b, _ in BENCHES) / 5 for e in names}
print(f"share vs mean-absolute tau_b {tau_b([base[e] for e in names], [absm[e] for e in names]):.3f}")
rm = sorted(names, key=lambda e: -absm[e])
print("moves", {e: rm.index(e) - names.index(e) for e in names if rm.index(e) != names.index(e)})
print(f"range {min(base.values()) * 100:.1f}-{max(base.values()) * 100:.1f}")
