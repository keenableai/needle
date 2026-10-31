import collections
import glob
import json
import math
import os
import sys

from needle.shared.metrics import normalize_url

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import account_side  # noqa: E402

site, out_path = sys.argv[1], sys.argv[2]
table_runs = {ts.replace(":", "") for ts in json.load(open(sys.argv[3]))["runs"]} if len(sys.argv) > 3 else None
LO, HI = "2026-10-17", "2026-10-30"
KEEP = "keenable exa google bing brave brave-llmcontext parallel perplexity tavily linkup tinyfish octen ceramic you firecrawl kagi jina context deepseek claude-search chatgpt-search".split()
GAIN = {4: 1.0, 3: 0.667, 2: 0.117, 1: 0.0, 0: 0.0}
K = 5
BENCHES = {"news": ("hfnews", "ndcg.json", "judged"), "agentic_rare": ("hfrare", "agentic_rare.json", "judged"),
           "scholar": ("hfscholar", "scholar.json", "hit"), "finance": ("hf", "recall.json", "hit"), "legal": ("hflegal", "legal.json", "hit")}


def dcg(ratings):
    return sum(GAIN.get(r, 0.0) / math.log2(i + 2) for i, r in enumerate(ratings[:K]))


def idcg(pool):
    return dcg(sorted(pool.values(), reverse=True)[:K])


result = {}
for bench, (folder, report, kind) in BENCHES.items():
    full = collections.defaultdict(lambda: [0.0, 0])
    loo = collections.defaultdict(lambda: [0.0, 0])
    zero_wo = collections.Counter()
    nq = 0
    nruns = 0
    for d in sorted(glob.glob(os.path.join(site, folder, "*"))):
        name = os.path.basename(d)
        if not (LO <= name[:10] < HI) or not os.path.exists(os.path.join(d, report)):
            continue
        if table_runs is not None and name not in table_runs:
            continue
        rep = json.load(open(os.path.join(d, report)))
        pqs = {}
        for e in KEEP:
            if e in rep["engines"]:
                p = os.path.join(d, rep["engines"][e].get("per_query_path", ""))
                if os.path.isfile(p):
                    pqs[e] = json.load(open(p))["per_query"]
        if len(pqs) < 19:
            continue
        nruns += 1
        n = len(next(iter(pqs.values())))
        for qi in range(n):
            contrib = {}
            for e, pq in pqs.items():
                r = pq[qi]
                if r.get("search_error") and account_side(r["search_error"]):
                    continue
                if kind == "judged":
                    best = {}
                    for x in r.get("results") or []:
                        if x.get("rating") is None:
                            continue
                        key = normalize_url(x["url"])
                        best[key] = max(best.get(key, 0), x["rating"])
                    contrib[e] = (best, dcg(r.get("penalized_ratings") or []))
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
                    continue
                nq += 1
                for e, (best, d_e) in contrib.items():
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
                nq += 1
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
        l = loo[e][0] / loo[e][1] if loo[e][1] else None
        rows[e] = {"full": f, "loo": l, "delta": (l - f) if l is not None else None, "n": full[e][1], "dropped_zero_ideal": zero_wo[e]}
    result[bench] = {"runs": nruns, "queries": nq, "engines": rows}
    deltas = [abs(v["delta"]) for v in rows.values() if v.get("delta") is not None]
    order_f = sorted(rows, key=lambda e: -rows[e]["full"])
    order_l = sorted(rows, key=lambda e: -(rows[e]["loo"] or 0))
    print(bench, "runs", nruns, "queries", nq, "max |delta| %.4f" % max(deltas), "order unchanged", order_f == order_l,
          "dropped (zero ideal without engine) total", sum(zero_wo.values()), "max per engine", max(zero_wo.values()) if zero_wo else 0, max(zero_wo, key=zero_wo.get) if zero_wo else "")

overall = {}
for e in KEEP:
    if all(e in result[b]["engines"] and result[b]["engines"][e]["loo"] is not None for b in result):
        f = sum(result[b]["engines"][e]["full"] for b in result) / len(result)
        l = sum(result[b]["engines"][e]["loo"] for b in result) / len(result)
        overall[e] = {"full": f, "loo": l, "delta": l - f}
of_ = sorted(overall, key=lambda e: -overall[e]["full"])
ol_ = sorted(overall, key=lambda e: -overall[e]["loo"])
print("overall max |delta| %.4f" % max(abs(v["delta"]) for v in overall.values()), "order unchanged", of_ == ol_, [(a, b) for a, b in zip(of_, ol_) if a != b])
for b in result:
    e = result[b]["engines"]
    o1 = sorted(e, key=lambda k: -e[k]["full"]); o2 = sorted(e, key=lambda k: -(e[k]["loo"] or 0))
    print("  ", b, "position changes", [(a, c) for a, c in zip(o1, o2) if a != c])
result["overall"] = overall
json.dump(result, open(out_path, "w"), indent=1)
