import collections
import glob
import json
import os
import random
import sys
from datetime import datetime

from common import KEEP, pct, tau_b
from query_values import values

site = sys.argv[1]
LO, HI = "2026-10-17", "2026-10-30"
MAX_LAG_S = 300
rng = random.Random(3)


def ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ")


rows = []
for d in sorted(glob.glob(os.path.join(site, "hfnews", "*"))):
    name = os.path.basename(d)
    if not (LO <= name[:10] < HI) or not os.path.exists(os.path.join(d, "ndcg.json")):
        continue
    rep = json.load(open(os.path.join(d, "ndcg.json")))
    pqs = {}
    for e in KEEP + ["ultimate"]:
        if e in rep["engines"]:
            p = os.path.join(d, rep["engines"][e].get("per_query_path", ""))
            if os.path.isfile(p):
                pqs[e] = json.load(open(p))["per_query"]
    engines = [e for e in KEEP if e in pqs]
    if len(engines) < 19 or "ultimate" not in pqs:
        continue
    ceiling = [q["ndcg"] is not None for q in pqs["ultimate"]]
    vals = {e: values("news", e, pqs[e], None, ceiling) for e in engines}
    for qi in range(len(ceiling)):
        t = {e: ts(pqs[e][qi]["queried_at"]) for e in engines if pqs[e][qi].get("queried_at")}
        if len(t) < 10:
            continue
        t0 = min(t.values())
        rows.extend({"run": name, "q": qi, "e": e, "score": vals[e][qi], "lag": (t[e] - t0).total_seconds()} for e in t if vals[e][qi] is not None)


def means(sel):
    acc = collections.defaultdict(list)
    for r in sel:
        acc[r["e"]].append(r["score"])
    return {e: sum(v) / len(v) for e, v in acc.items()}, {e: len(v) for e, v in acc.items()}


full, n_full = means(rows)
sel = [r for r in rows if r["lag"] <= MAX_LAG_S]
sub, n_sub = means(sel)
engines = sorted(e for e in full if e in sub and n_sub[e] >= 30)
tb = tau_b([full[e] for e in engines], [sub[e] for e in engines])
clusters = collections.defaultdict(list)
for r in sel:
    clusters[(r["run"], r["q"])].append(r)
cl = list(clusters.values())
diffs = collections.defaultdict(list)
for _ in range(500):
    mb, _n = means([r for _k in range(len(cl)) for r in cl[rng.randrange(len(cl))]])
    for e in engines:
        if e in mb:
            diffs[e].append(mb[e] - full[e])
ci = {e: (pct(diffs[e], .025), pct(diffs[e], .975)) for e in engines}
moved = sorted(engines, key=lambda e: -abs(sub[e] - full[e]))
runs = {r["run"] for r in rows}
queries = {(r["run"], r["q"]) for r in rows}
print(f"scored: runs {len(runs)} query-runs {len(queries)} pairs {len(rows)}; lag <= {MAX_LAG_S} s keeps {len(sel)} ({len(sel) / len(rows):.3f}); engines {len(engines)} tau_b vs full {tb:.3f}")
for e in moved[:3]:
    print(f"   {e:17s} n {n_sub[e]:4d} full {full[e]:.3f} subset {sub[e]:.3f} diff {sub[e] - full[e]:+.3f} ci [{ci[e][0]:+.3f},{ci[e][1]:+.3f}]")
json.dump({"runs": len(runs), "query_runs": len(queries), "pairs": len(rows), "max_lag_s": MAX_LAG_S, "kept_pairs": len(sel), "kept_share": len(sel) / len(rows),
           "engines": len(engines), "tau_b": tb, "full": full, "n_full": n_full, "subset": sub, "n_subset": n_sub, "ci_diff": ci,
           "max_move": {"engine": moved[0], "diff": sub[moved[0]] - full[moved[0]]}}, open(sys.argv[2], "w"), indent=1)
