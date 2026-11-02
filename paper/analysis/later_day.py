import glob
import json
import os
import sys
from urllib.parse import urlsplit

from common import BENCHES, NAMES, kept_engines, load, order_tau, overall, shares

site, hist_path, pairs_json, out_rows, out_json = sys.argv[1:6]
REPORTS = {"news": "ndcg.json", "agentic_rare": "agentic_rare.json", "scholar": "scholar.json"}


def ts_of(name):
    return name[:13] + ":" + name[13:15] + "Z"


goto = {}
for bench, report in REPORTS.items():
    for d in sorted(glob.glob(os.path.join(site, bench, "*"))):
        p = os.path.join(d, report)
        if not os.path.exists(p):
            continue
        rep = json.load(open(p))
        for eng, e in rep["engines"].items():
            pq_path = os.path.join(d, e.get("per_query_path", ""))
            if eng in ("google", "jina") and os.path.isfile(pq_path):
                n = g = 0
                for q in json.load(open(pq_path))["per_query"]:
                    for r in q.get("results") or []:
                        n += 1
                        g += "google.com" in (urlsplit(r["url"]).hostname or "") and "/goto" in urlsplit(r["url"]).path
                goto.setdefault(eng, [0, 0])
                goto[eng][0] += g
                goto[eng][1] += n
hist = load(hist_path)
later_runs = {(b, ts_of(os.path.basename(d))) for b, _ in BENCHES for d in glob.glob(os.path.join(site, b, "*"))}
rows = [r for r in hist if (r["bench"], r["ts"]) in later_runs]
assert {(r["bench"], r["ts"]) for r in rows} == later_runs, later_runs - {(r["bench"], r["ts"]) for r in rows}
with open(out_rows, "w") as f:
    for r in rows:
        f.write(json.dumps(r) + "\n")
print("rows", len(rows), "runs per bench", {b: len({r["ts"] for r in rows if r["bench"] == b}) for b, _ in BENCHES})
print("goto share", {e: round(v[0] / v[1], 3) for e, v in goto.items() if v[1]})

table = [r for r in hist if r["ts"] in set(json.load(open(pairs_json))["runs"])]
keep = kept_engines({r["engine"] for r in table})
sh_t, ult_t = shares(table, keep)
sh_l, ult_l = shares(rows, keep)
o_t = {e: overall(sh_t, e) for e in keep if overall(sh_t, e) is not None}
o_l = {e: overall(sh_l, e) for e in keep if overall(sh_l, e) is not None}
common_e = [e for e in o_t if e in o_l]
order_t = sorted(common_e, key=lambda e: -o_t[e])
order_l = sorted(common_e, key=lambda e: -o_l[e])

print(f"engines with all five benches: {len(common_e)}; overall tau_b {order_tau(order_t, order_l):.3f}")
res = {"engines": {}, "tau_b_overall": order_tau(order_t, order_l), "bench_tau": {}, "goto": goto, "runs": {b: len({r['ts'] for r in rows if r['bench'] == b}) for b, _ in BENCHES}}
for b, _ in BENCHES:
    es = [e for e in common_e if sh_t[e][b][1] is not None and sh_l[e][b][1] is not None]
    ot = sorted(es, key=lambda e: -sh_t[e][b][1])
    ol = sorted(es, key=lambda e: -sh_l[e][b][1])
    res["bench_tau"][b] = order_tau(ot, ol)
    print(f"  {b:13s} tau_b {order_tau(ot, ol):.3f} ceiling table {ult_t[b]:.3f} later day {ult_l[b]:.3f}")
for e in order_t:
    res["engines"][e] = {"table": o_t[e], "later_day": o_l[e], "rank_table": order_t.index(e) + 1, "rank_later_day": order_l.index(e) + 1,
                         "errors": sum(r["search_errors"] for r in rows if r["engine"] == e), "requests": sum(r["num_queries"] for r in rows if r["engine"] == e)}
    print(f"  {NAMES.get(e, e):18s} table {100 * o_t[e]:.1f} (rank {order_t.index(e) + 1}) -> later day {100 * o_l[e]:.1f} (rank {order_l.index(e) + 1}); errors {res['engines'][e]['errors']}/{res['engines'][e]['requests']}")
missing = [e for e in o_t if e not in o_l]
print("engines without a full later-day set:", missing)
json.dump(res, open(out_json, "w"), indent=1)
