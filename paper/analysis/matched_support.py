import collections
import glob
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from needle.shared.search.errors import account_side  # noqa: E402
from strict_v2 import finance_run  # noqa: E402

site, out_json = sys.argv[1], sys.argv[2]
LO, HI = "2026-10-17", "2026-10-30"
KEEP = "keenable exa google bing brave brave-llmcontext parallel perplexity tavily linkup tinyfish octen ceramic you firecrawl kagi jina context deepseek claude-search chatgpt-search".split()
BENCHES = {
    "scholar": ("hfscholar", "scholar.json", "hit"),
    "news": ("hfnews", "ndcg.json", "ndcg"),
    "finance": ("hf", "recall.json", "hit"),
    "agentic_rare": ("hfrare", "agentic_rare.json", "ndcg"),
    "legal": ("hflegal", "legal.json", "hit"),
}
rng = random.Random(3)


def value(pq, kind):
    if kind == "ndcg":
        return float(pq.get("ndcg") or 0.0)
    return 1.0 if pq.get("hit_rank") is not None else 0.0


def tau_b(a, b):
    n = len(a)
    c = d = ta = tb = 0
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


per_bench = {}
retained = {}
for bench, (folder, report, kind) in BENCHES.items():
    rows = []
    n_runs = 0
    for d in sorted(glob.glob(os.path.join(site, folder, "*"))):
        name = os.path.basename(d)
        if not (LO <= name[:10] < HI) or not os.path.exists(os.path.join(d, report)):
            continue
        rep = json.load(open(os.path.join(d, report)))
        pqs = {}
        for e in KEEP + ["ultimate"]:
            if e in rep["engines"]:
                p = os.path.join(d, rep["engines"][e].get("per_query_path", ""))
                if os.path.isfile(p):
                    pqs[e] = json.load(open(p))["per_query"]
                elif "per_query" in rep["engines"][e]:
                    pqs[e] = rep["engines"][e]["per_query"]
        present = [e for e in KEEP if e in pqs]
        if len(present) < 20 or "ultimate" not in pqs:
            continue
        if bench == "finance":
            pqs = {e: v["per_query"] for e, v in finance_run(d)[0]["engines"].items() if e in pqs}
        n_runs += 1
        for qi in range(len(pqs["ultimate"])):
            acct_fail = any(pqs[e][qi].get("search_error") is not None and account_side(pqs[e][qi]["search_error"]) for e in present)
            vals = {}
            for e in present:
                pq = pqs[e][qi]
                failed = pq.get("search_error") is not None
                vals[e] = pq["score"] if bench == "finance" else None if (failed and account_side(pq["search_error"])) else (0.0 if failed else value(pq, kind))
            rows.append({"u": value(pqs["ultimate"][qi], kind), "vals": vals, "acct_fail": acct_fail})
    per_bench[bench] = rows
    retained[bench] = {"runs": n_runs, "queries": len(rows), "matched_queries": sum(1 for r in rows if not r["acct_fail"])}


def shares(rows_by_bench, matched):
    out = collections.defaultdict(dict)
    for bench, rows in rows_by_bench.items():
        use = [r for r in rows if not (matched and r["acct_fail"])]
        if not use:
            continue
        u = sum(r["u"] for r in use) / len(use)
        for e in KEEP:
            vs = [r["vals"][e] for r in use if r["vals"].get(e) is not None]
            if vs:
                out[e][bench] = sum(vs) / len(vs) / u
    return out


def overall(sh):
    return {e: sum(b.values()) / len(b) for e, b in sh.items() if len(b) == len(per_bench)}


base = overall(shares(per_bench, False))
matched = overall(shares(per_bench, True))
names = [e for e in KEEP if e in base and e in matched]
tau = tau_b([base[e] for e in names], [matched[e] for e in names])
ob = sorted(names, key=lambda e: -base[e])
om = sorted(names, key=lambda e: -matched[e])

diffs = collections.defaultdict(list)
for _ in range(1000):
    sample = {b: [rows[rng.randrange(len(rows))] for _ in rows] for b, rows in per_bench.items()}
    b1, m1 = overall(shares(sample, False)), overall(shares(sample, True))
    for e in names:
        if e in b1 and e in m1:
            diffs[e].append(m1[e] - b1[e])
ci = {}
for e in names:
    xs = sorted(diffs[e])
    ci[e] = (xs[int(0.025 * len(xs))], xs[int(0.975 * len(xs))])

json.dump({"retained": retained, "base": base, "matched": matched, "tau_b": tau, "ci_diff": ci}, open(out_json, "w"), indent=1)
print("retained", retained)
print("tau_b base vs matched %.3f" % tau)
for e in ob:
    print(f"  {e:17s} base {base[e]*100:5.1f} (rank {ob.index(e)+1:2d})  matched {matched[e]*100:5.1f} (rank {om.index(e)+1:2d})  diff {100*(matched[e]-base[e]):+.1f} [{100*ci[e][0]:+.1f},{100*ci[e][1]:+.1f}]")
