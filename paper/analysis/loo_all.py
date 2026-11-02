import collections
import glob
import json
import os
import sys

from common import KEEP, ULT
from finance_runs import finance_run

from needle.shared.metrics import dcg_at_k, normalize_url
from needle.shared.rankeval import QueryRun, _fully_judged
from needle.shared.search.errors import account_side

site, out_path, pairs_json = sys.argv[1], sys.argv[2], sys.argv[3]
table_runs = {ts.replace(":", "") for ts in json.load(open(pairs_json))["runs"]}
BENCHES = {"news": ("hfnews", "ndcg.json", "judged"), "agentic_rare": ("hfrare", "agentic_rare.json", "judged"),
           "scholar": ("hfscholar", "scholar.json", "hit"), "finance": ("hf", "recall.json", "hit"), "legal": ("hflegal", "legal.json", "hit")}


def idcg(pool):
    return dcg_at_k(sorted(pool.values(), reverse=True))


result = {}
for bench, (folder, report, kind) in BENCHES.items():
    full = collections.defaultdict(lambda: [0.0, 0])
    loo = collections.defaultdict(lambda: [0.0, 0])
    zero_wo = collections.Counter()
    query_runs = collections.Counter()
    nruns = 0
    for d in sorted(glob.glob(os.path.join(site, folder, "*"))):
        name = os.path.basename(d)
        if name not in table_runs or not os.path.exists(os.path.join(d, report)):
            continue
        rep = json.load(open(os.path.join(d, report)))
        paths = {e: os.path.join(d, v.get("per_query_path", "")) for e, v in rep["engines"].items() if e != ULT}
        if kind == "judged" and not all(os.path.isfile(p) for p in paths.values()):
            continue
        run_pqs = {e: json.load(open(p))["per_query"] for e, p in paths.items() if (kind == "judged" or e in KEEP) and os.path.isfile(p)}
        pqs = {e: run_pqs[e] for e in KEEP if e in run_pqs}
        if len(pqs) < 19:
            continue
        if bench == "finance":
            pqs = {e: v["per_query"] for e, v in finance_run(d)[0]["engines"].items() if e in pqs}
        nruns += 1
        n = len(next(iter(pqs.values())))
        for qi in range(n):
            if kind == "judged" and not _fully_judged(QueryRun(searches=[], judgements=[pq[qi]["ratings"] for pq in run_pqs.values()], n_judged=0, profile=None)):
                query_runs["judge_error"] += 1
                continue
            contrib = {}
            for e, pq in pqs.items():
                r = pq[qi]
                if (r.get("search_error") and account_side(r["search_error"])) or (bench == "finance" and r["score"] is None):
                    continue
                if kind == "judged":
                    best = {}
                    for x in r.get("results") or []:
                        key = normalize_url(x["url"])
                        best[key] = max(best.get(key, 0), x["rating"])
                    contrib[e] = (best, dcg_at_k(r.get("penalized_ratings") or []))
                else:
                    contrib[e] = (r.get("hit_rank") is not None, None)
            if not contrib:
                continue
            if kind == "judged":
                pool = {}
                for best, _ in contrib.values():
                    for u, g in best.items():
                        pool[u] = max(pool.get(u, 0), g)
                ideal = idcg(pool)
                if ideal <= 0:
                    query_runs["empty_ceiling"] += 1
                    continue
                query_runs["scored"] += 1
                for e, (_, d_e) in contrib.items():
                    full[e][0] += d_e / ideal
                    full[e][1] += 1
                    pool_wo = {}
                    for o, (b2, _) in contrib.items():
                        if o != e:
                            for u, g in b2.items():
                                pool_wo[u] = max(pool_wo.get(u, 0), g)
                    iw = idcg(pool_wo)
                    if iw > 0:
                        loo[e][0] += d_e / iw
                        loo[e][1] += 1
                    else:
                        zero_wo[e] += 1
            else:
                hits = {e: h for e, (h, _) in contrib.items()}
                query_runs["scored"] += 1
                for e, h in hits.items():
                    full[e][1] += 1 if any(hits.values()) else 0
                    full[e][0] += 1.0 if h else 0.0
                    others = any(v for o, v in hits.items() if o != e)
                    loo[e][1] += 1 if others else 0
                    loo[e][0] += 1.0 if (h and others) else 0.0
    rows = {}
    for e in KEEP:
        if e not in full or not full[e][1]:
            continue
        f = full[e][0] / full[e][1]
        lv = loo[e][0] / loo[e][1] if loo[e][1] else None
        rows[e] = {"full": f, "loo": lv, "delta": (lv - f) if lv is not None else None, "n": full[e][1], "dropped_zero_ideal": zero_wo[e]}
    result[bench] = {"runs": nruns, "query_runs": dict(sorted(query_runs.items())), "engines": rows}
    deltas = [abs(v["delta"]) for v in rows.values() if v.get("delta") is not None]
    order_f = sorted(rows, key=lambda e: -rows[e]["full"])
    order_l = sorted(rows, key=lambda e: -(rows[e]["loo"] or 0))
    print(bench, "runs", nruns, "query_runs", dict(sorted(query_runs.items())), f"max |delta| {max(deltas):.4f}", "order unchanged", order_f == order_l,
          "dropped (zero ideal without engine) total", sum(zero_wo.values()), "max per engine", max(zero_wo.values()) if zero_wo else 0, max(zero_wo, key=zero_wo.get) if zero_wo else "")

overall = {}
for e in KEEP:
    if all(e in result[b]["engines"] and result[b]["engines"][e]["loo"] is not None for b in result):
        f = sum(result[b]["engines"][e]["full"] for b in result) / len(result)
        lv = sum(result[b]["engines"][e]["loo"] for b in result) / len(result)
        overall[e] = {"full": f, "loo": lv, "delta": lv - f}
full_order = sorted(overall, key=lambda e: -overall[e]["full"])
loo_order = sorted(overall, key=lambda e: -overall[e]["loo"])
print(f"overall max |delta| {max(abs(v['delta']) for v in overall.values()):.4f}", "order unchanged", full_order == loo_order, [(a, b) for a, b in zip(full_order, loo_order, strict=True) if a != b])
for b in result:
    e = result[b]["engines"]
    o1 = sorted(e, key=lambda k: -e[k]["full"])
    o2 = sorted(e, key=lambda k: -(e[k]["loo"] or 0))
    print("  ", b, "position changes", [(a, c) for a, c in zip(o1, o2, strict=True) if a != c])
result["overall"] = overall
result["overall_order"] = {"full": full_order, "loo": loo_order}
result["loo_lead"] = {"leader": loo_order[0], "second": loo_order[1], "points": 100 * (overall[loo_order[0]]["loo"] - overall[loo_order[1]]["loo"])}
json.dump(result, open(out_path, "w"), indent=1)
