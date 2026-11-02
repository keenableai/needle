import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from needle.shared.metrics import dcg_at_k, normalize_url
from needle.shared.search.errors import account_side

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import ULT, tau_b

hf_dir, pairs_json, runs_json, out_json = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]


def per_query_paths(ts):
    d = hf_dir / ts.replace(":", "")
    engines = json.load(open(d / "ndcg.json"))["engines"]
    return {e: d / v.get("per_query_path", "") for e, v in engines.items() if e != ULT}


def idcg(pools):
    pool = {}
    for best in pools:
        for u, g in best.items():
            pool[u] = max(pool.get(u, 0), g)
    return dcg_at_k(sorted(pool.values(), reverse=True))


runs, incomplete = [], []
for ts in sorted(json.load(open(pairs_json))["runs"]):
    run_dir = hf_dir / ts.replace(":", "")
    if run_dir.is_dir():
        complete = (run_dir / "ndcg.json").exists() and all(p.is_file() for p in per_query_paths(ts).values())
        (runs if complete else incomplete).append(ts)
json.dump({"source": "news runs of audit/adjacent_pairs.json; incomplete lack the report or a configuration's per-query file",
           "runs": runs, "incomplete": incomplete}, open(runs_json, "w"), indent=1)

full = defaultdict(list)
loo = defaultdict(list)
emptied = Counter()
query_runs = Counter()
for ts in runs:
    pqs = {e: json.load(open(p))["per_query"] for e, p in per_query_paths(ts).items()}
    for row in zip(*pqs.values(), strict=True):
        if any(pq["judge_errors"] for pq in row):
            query_runs["judge_error"] += 1
            continue
        best, dcg = {}, {}
        for e, pq in zip(pqs, row, strict=True):
            err = pq["search_error"]
            if err is None:
                b = {}
                for r in pq["results"]:
                    u = normalize_url(r["url"])
                    b[u] = max(b.get(u, 0), r["rating"])
                best[e] = b
                dcg[e] = dcg_at_k(pq["penalized_ratings"])
            elif not account_side(err):
                dcg[e] = 0.0
        ideal = idcg(best.values())
        if ideal <= 0:
            query_runs["empty_ceiling"] += 1
            continue
        query_runs["scored"] += 1
        for e, d in dcg.items():
            full[e].append(d / ideal)
            ideal_wo = idcg(b for o, b in best.items() if o != e)
            if ideal_wo > 0:
                loo[e].append(d / ideal_wo)
            else:
                emptied[e] += 1

names = sorted(full)
mean_full = {e: sum(full[e]) / len(full[e]) for e in names}
mean_loo = {e: sum(loo[e]) / len(loo[e]) for e in names}
delta = {e: mean_loo[e] - mean_full[e] for e in names}
order_full = sorted(names, key=lambda e: -mean_full[e])
order_loo = sorted(names, key=lambda e: -mean_loo[e])
top = max(names, key=lambda e: abs(delta[e]))
engines = {e: {"n": len(full[e]), "full": round(mean_full[e], 4), "loo": round(mean_loo[e], 4), "delta": round(delta[e], 4),
               "exceed_frac": round(sum(x > 1 for x in loo[e]) / len(loo[e]), 4), "emptied": emptied[e]} for e in order_full}
summary = {
    "runs": len(runs), "first": runs[0], "last": runs[-1], "query_runs": dict(query_runs),
    "largest_delta": {"engine": top, "delta": round(delta[top], 4), "n": len(full[top])},
    "max_other_abs_delta": round(max(abs(delta[e]) for e in names if e != top), 4),
    "max_exceed_frac": max(o["exceed_frac"] for o in engines.values()), "emptied": sum(emptied.values()),
    "tau_b": round(tau_b([mean_full[e] for e in names], [mean_loo[e] for e in names]), 4),
    "order_full": order_full, "order_loo": order_loo,
}
for e, o in engines.items():
    print(f"{e:20s} n={o['n']:5d} full={o['full']:.4f} loo={o['loo']:.4f} d={o['delta']:+.4f} >1:{o['exceed_frac']:.4f} emptied={o['emptied']}")
print(json.dumps(summary))
json.dump({**summary, "engines": engines}, open(out_json, "w"), indent=1)
