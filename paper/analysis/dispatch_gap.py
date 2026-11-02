import collections
import glob
import json
import os
import sys
from datetime import datetime

from common import KEEP, pct

site, out_json = sys.argv[1], sys.argv[2]
LO, HI = "2026-10-17", "2026-10-30"
SLOW_S = 30


def ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ")


queries = []
runs = set()
for d in sorted(glob.glob(os.path.join(site, "hfnews", "*"))):
    name = os.path.basename(d)
    if not (LO <= name[:10] < HI) or not os.path.exists(os.path.join(d, "ndcg.json")):
        continue
    rep = json.load(open(os.path.join(d, "ndcg.json")))
    pqs = {}
    for e in KEEP:
        if e in rep["engines"]:
            p = os.path.join(d, rep["engines"][e].get("per_query_path", ""))
            if os.path.isfile(p):
                pqs[e] = json.load(open(p))["per_query"]
    if len(pqs) < 19:
        continue
    for qi in range(len(next(iter(pqs.values())))):
        recs = {e: pqs[e][qi] for e in pqs if pqs[e][qi].get("queried_at")}
        if len(recs) < 10:
            continue
        queries.append(({e: ts(r["queried_at"]) for e, r in recs.items()}, {e for e, r in recs.items() if r["search_error"] is None}))
        runs.add(name)

lags = collections.defaultdict(list)
for t, answered in queries:
    t0 = min(t.values())
    for e in answered:
        lags[e].append((t[e] - t0).total_seconds())
lag_mean = {e: sum(v) / len(v) for e, v in sorted(lags.items())}
slow = sorted(e for e, v in lag_mean.items() if v >= SLOW_S)


def spread(t, drop):
    kept = [v for e, v in t.items() if e not in drop]
    return (max(kept) - min(kept)).total_seconds()


full = [spread(t, ()) for t, _ in queries]
fast = [spread(t, slow) for t, _ in queries]
print("news runs", len(runs), "query-runs", len(queries))
print(f"same-query dispatch spread (s): median {pct(full, .5):.0f}, p90 {pct(full, .9):.0f}")
print(f"mean lag of answered requests (s), {sum(v < SLOW_S for v in lag_mean.values())} engines under {SLOW_S}:", {e: round(lag_mean[e], 1) for e in sorted(lag_mean, key=lag_mean.get)})
print(f"spread without {slow} (s): median {pct(fast, .5):.0f}, p90 {pct(fast, .9):.0f}")
json.dump({"runs": len(runs), "query_runs": len(queries), "lag_mean_s": lag_mean, "under_30s": sum(v < SLOW_S for v in lag_mean.values()), "slow": slow,
           "spread_s": {"median": pct(full, .5), "p90": pct(full, .9)}, "spread_without_slow_s": {"median": pct(fast, .5), "p90": pct(fast, .9)}},
          open(out_json, "w"), indent=1)
