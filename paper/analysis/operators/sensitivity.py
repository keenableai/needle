import json
import sys
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

from needle.shared.metrics import GAIN, dcg_at_k, normalize_url

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import tau_b

hf_dir = Path(sys.argv[1])
K = 5
GAINS = {
    "default": dict(GAIN),
    "linear": {4: 1.0, 3: 0.75, 2: 0.5, 1: 0.25, 0: 0.0},
    "exp2": {4: 1.0, 3: 7 / 15, 2: 3 / 15, 1: 1 / 15, 0: 0.0},
    "binary>=3": {4: 1.0, 3: 1.0, 2: 0.0, 1: 0.0, 0: 0.0},
    "binary=4": {4: 1.0, 3: 0.0, 2: 0.0, 1: 0.0, 0: 0.0},
    "binary>=2": {4: 1.0, 3: 1.0, 2: 1.0, 1: 0.0, 0: 0.0},
}


runs = sorted(p for p in hf_dir.iterdir() if p.is_dir() and (p / "ndcg.json").exists())
queries = []
for run in runs:
    rep = json.load(open(run / "ndcg.json"))
    by_query = {}
    for name, e in rep["engines"].items():
        p = run / e.get("per_query_path", "")
        if name == "ultimate" or not p.exists():
            continue
        for pq in json.load(open(p))["per_query"]:
            if pq["search_error"] is not None or pq.get("judge_errors"):
                continue
            by_query.setdefault(pq["query"], {})[name] = pq
    for d in by_query.values():
        pool = {}
        ratings = {}
        for name, pq in d.items():
            ratings[name] = pq["penalized_ratings"]
            for r in pq["results"]:
                if r.get("rating") is None:
                    continue
                u = normalize_url(r["url"])
                pool[u] = max(pool.get(u, 0), r["rating"])
        queries.append((sorted(pool.values(), reverse=True), ratings))
print("queries", len(queries))


def scores(g, include_zero):
    acc = defaultdict(list)
    with patch.dict(GAIN, g, clear=True):
        for pool, ratings in queries:
            idcg = dcg_at_k(pool, k=K)
            if idcg <= 0:
                if include_zero:
                    for name in ratings:
                        acc[name].append(0.0)
                continue
            for name, r in ratings.items():
                acc[name].append(dcg_at_k(r, k=K) / idcg)
    return {k: sum(v) / len(v) for k, v in acc.items() if len(v) >= 500}


base = scores(GAINS["default"], False)
names = sorted(base, key=lambda n: -base[n])
rank_base = {n: i for i, n in enumerate(names)}
print("engines", len(names))
variants = [(k, g, False) for k, g in GAINS.items()] + [("default+idcg0", GAINS["default"], True)]
for label, g, inc in variants:
    s = scores(g, inc)
    ranked = sorted(names, key=lambda n: -s[n])
    rank = {n: i for i, n in enumerate(ranked)}
    moves = {n: rank[n] - rank_base[n] for n in names}
    big = {n: m for n, m in moves.items() if abs(m) >= 2}
    print(f"{label:14s} tau_b={tau_b([base[n] for n in names], [s[n] for n in names]):.3f} max|rank move|={max(abs(m) for m in moves.values())} moves>=2: {big}")
