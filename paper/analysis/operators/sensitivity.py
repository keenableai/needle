import json
import sys
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

from needle.shared.metrics import GAIN, dcg_at_k, normalize_url
from needle.shared.search.errors import account_side

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import ULT, tau_b

hf_dir, runs_json, out_json = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
GAINS = {
    "linear": {4: 1.0, 3: 0.75, 2: 0.5, 1: 0.25, 0: 0.0},
    "exp2": {4: 1.0, 3: 7 / 15, 2: 3 / 15, 1: 1 / 15, 0: 0.0},
    "binary>=3": {4: 1.0, 3: 1.0, 2: 0.0, 1: 0.0, 0: 0.0},
    "binary=4": {4: 1.0, 3: 0.0, 2: 0.0, 1: 0.0, 0: 0.0},
    "binary>=2": {4: 1.0, 3: 1.0, 2: 1.0, 1: 0.0, 0: 0.0},
}


runs = json.load(open(runs_json))["runs"]
queries = []
for ts in runs:
    d = hf_dir / ts.replace(":", "")
    engines = json.load(open(d / "ndcg.json"))["engines"]
    pqs = {e: json.load(open(d / v["per_query_path"]))["per_query"] for e, v in engines.items() if e != ULT}
    for row in zip(*pqs.values(), strict=True):
        if any(pq["judge_errors"] for pq in row):
            continue
        pool = {}
        ratings = {}
        for e, pq in zip(pqs, row, strict=True):
            err = pq["search_error"]
            if err is not None:
                if not account_side(err):
                    ratings[e] = []
                continue
            ratings[e] = pq["penalized_ratings"]
            for r in pq["results"]:
                u = normalize_url(r["url"])
                pool[u] = max(pool.get(u, 0), r["rating"])
        queries.append((sorted(pool.values(), reverse=True), ratings))


def scores(g):
    acc = defaultdict(list)
    n = 0
    with patch.dict(GAIN, g, clear=True):
        for pool, ratings in queries:
            ideal = dcg_at_k(pool)
            if ideal <= 0:
                continue
            n += 1
            for e, r in ratings.items():
                acc[e].append(dcg_at_k(r) / ideal)
    return {e: sum(v) / len(v) for e, v in acc.items()}, n


base, n_base = scores(dict(GAIN))
names = sorted(base, key=lambda e: (-base[e], e))
out = {"runs": len(runs), "query_runs": n_base, "order": names, "variants": {}}
print("runs", len(runs), "query_runs", n_base, "engines", len(names))
for label, g in GAINS.items():
    s, n = scores(g)
    ranked = sorted(names, key=lambda e: (-s[e], e))
    places_up = {e: i - ranked.index(e) for i, e in enumerate(names)}
    top = max(abs(m) for m in places_up.values())
    v = out["variants"][label] = {
        "query_runs": n, "tau_b": round(tau_b([base[e] for e in names], [s[e] for e in names]), 4), "max_rank_move": top,
        "places_up": {e: m for e, m in places_up.items() if m}, "order": ranked,
    }
    print(f"{label:10s} query_runs={n} tau_b={v['tau_b']:.4f} max|rank move|={top} places_up: {v['places_up']}")
json.dump(out, open(out_json, "w"), indent=1)
