import json
import random
import sys
from pathlib import Path

from common import ci, spearman

from needle.shared.metrics import apply_redundancy_penalties, dcg_at_k, normalize_url

rng = random.Random(9)


def run(sample_dir, minq):
    d = Path(sample_dir)
    key = {int(k): v for k, v in json.load(open(d / "key.json")).items()}
    queries = json.load(open(d / "queries.json"))
    opus = {}
    for f in sorted(d.glob("labels_part*.json")):
        for row in json.load(open(f)):
            opus[int(row["id"])] = int(row["rating"])
    gpt = {i: key[i]["gpt"] for i in key}

    def per_query_scores(rating_of):
        out = []
        for q in queries:
            pool = {}
            eng = {}
            for name, m in q["engines"].items():
                if any(i not in rating_of for i in m["positions"]):
                    continue
                urls = [key[i]["url"] for i in m["positions"]]
                rs = [rating_of[i] for i in m["positions"]]
                for u, r in zip(urls, rs, strict=True):
                    pool[normalize_url(u)] = max(pool.get(normalize_url(u), 0), r)
                eng[name] = apply_redundancy_penalties(urls, rs, query_text=q["query"])
            idcg = dcg_at_k(sorted(pool.values(), reverse=True))
            out.append({n: dcg_at_k(rs) / idcg for n, rs in eng.items()} if idcg > 0 else {})
        return out

    pg, po = per_query_scores(gpt), per_query_scores(opus)
    engines = [e for e in sorted(set().union(*pg, *po)) if all(sum(1 for s in p if e in s) >= minq for p in (pg, po))]

    def agree(idx):
        sg = {e: [pg[i][e] for i in idx if e in pg[i]] for e in engines}
        so = {e: [po[i][e] for i in idx if e in po[i]] for e in engines}
        names = [e for e in engines if sg[e] and so[e]]
        if len(names) < 3:
            return None
        return spearman([sum(sg[e]) / len(sg[e]) for e in names], [sum(so[e]) / len(so[e]) for e in names])

    point = agree(range(len(queries)))
    boots = [v for v in (agree([rng.randrange(len(queries)) for _ in queries]) for _ in range(2000)) if v is not None]
    lo, hi = ci(boots)
    print(f"{sample_dir}: {len(engines)} engines, engine-level Spearman {point:.3f}, query-cluster bootstrap 95% CI {lo:.2f}..{hi:.2f} ({len(boots)} resamples)")
    return {"queries": len(queries), "minq": minq, "engines": engines, "spearman": point, "ci": [lo, hi], "resamples": len(boots)}


json.dump({"news": run(sys.argv[1], 6), "rare": run(sys.argv[2], 4)}, open(sys.argv[3], "w"), indent=1)
