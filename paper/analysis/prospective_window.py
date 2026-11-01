import glob
import json
import os
import sys
from urllib.parse import urlsplit

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import BENCHES, FAMILIES, NAMES, ULT, load, overall, shares  # noqa: E402

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
post = {(b, ts_of(os.path.basename(d))) for b, _ in BENCHES for d in glob.glob(os.path.join(site, b, "*"))}
rows = [r for r in hist if (r["bench"], r["ts"]) in post]
assert {(r["bench"], r["ts"]) for r in rows} == post, post - {(r["bench"], r["ts"]) for r in rows}
with open(out_rows, "w") as f:
    for r in rows:
        f.write(json.dumps(r) + "\n")
print("rows", len(rows), "runs per bench", {b: len({r["ts"] for r in rows if r["bench"] == b}) for b, _ in BENCHES})
print("goto share", {e: round(v[0] / v[1], 3) for e, v in goto.items() if v[1]})

pro = load(out_rows)
table = [r for r in hist if r["ts"] in set(json.load(open(pairs_json))["runs"])]
keep = [e for e in sorted({r["engine"] for r in table} - {ULT}) if e not in FAMILIES or e == "brave-llmcontext"]
sh_t, ult_t = shares(table, keep)
sh_p, ult_p = shares(pro, keep)
o_t = {e: overall(sh_t, e) for e in keep if overall(sh_t, e) is not None}
o_p = {e: overall(sh_p, e) for e in keep if overall(sh_p, e) is not None}
common_e = [e for e in o_t if e in o_p]
order_t = sorted(common_e, key=lambda e: -o_t[e])
order_p = sorted(common_e, key=lambda e: -o_p[e])


def tau_b(a, b):
    c = d = 0
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            x = (a.index(a[i]) - a.index(a[j])) * (b.index(a[i]) - b.index(a[j]))
            c += x > 0
            d += x < 0
    return (c - d) / (c + d)


print(f"engines with all five benches: {len(common_e)}; overall tau_b {tau_b(order_t, order_p):.3f}")
res = {"engines": {}, "tau_b_overall": tau_b(order_t, order_p), "bench_tau": {}, "goto": goto, "runs": {b: len({r['ts'] for r in rows if r['bench'] == b}) for b, _ in BENCHES}}
for b, _ in BENCHES:
    es = [e for e in common_e if sh_t[e][b][1] is not None and sh_p[e][b][1] is not None]
    ot = sorted(es, key=lambda e: -sh_t[e][b][1])
    op = sorted(es, key=lambda e: -sh_p[e][b][1])
    res["bench_tau"][b] = tau_b(ot, op)
    print(f"  {b:13s} tau_b {tau_b(ot, op):.3f} ceiling table {ult_t[b]:.3f} prospective {ult_p[b]:.3f}")
for e in order_t:
    res["engines"][e] = {"table": o_t[e], "prospective": o_p[e], "rank_table": order_t.index(e) + 1, "rank_prospective": order_p.index(e) + 1,
                         "errors": sum(r["search_errors"] for r in pro if r["engine"] == e), "requests": sum(r["num_queries"] for r in pro if r["engine"] == e)}
    print(f"  {NAMES.get(e, e):18s} table {100 * o_t[e]:.1f} (rank {order_t.index(e) + 1}) -> prospective {100 * o_p[e]:.1f} (rank {order_p.index(e) + 1}); errors {res['engines'][e]['errors']}/{res['engines'][e]['requests']}")
missing = [e for e in o_t if e not in o_p]
print("engines without a full prospective set:", missing)
json.dump(res, open(out_json, "w"), indent=1)
