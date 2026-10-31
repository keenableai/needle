import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

from needle.shared.metrics import GAIN, normalize_url

rng = random.Random(9)


def spearman(a, b):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i]); r = [0.0] * len(v)
        for pos, i in enumerate(order):
            r[i] = pos
        return r
    ra, rb = ranks(a), ranks(b); ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    return sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / (sum((x - ma) ** 2 for x in ra) ** 0.5 * sum((y - mb) ** 2 for y in rb) ** 0.5)


def dcg(r):
    return sum(GAIN.get(x, 0.0) / math.log2(i + 2) for i, x in enumerate(r[:5]))


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
            pool = {}; eng = {}
            for name, m in q["engines"].items():
                if any(i not in rating_of for i in m["positions"]):
                    continue
                seen = set(); rs = []
                for i in m["positions"]:
                    u = normalize_url(key[i]["url"]); r = rating_of[i]
                    rs.append(0 if u in seen else r); seen.add(u); pool[u] = max(pool.get(u, 0), r)
                eng[name] = rs
            idcg = dcg(sorted(pool.values(), reverse=True))
            out.append({n: dcg(rs) / idcg for n, rs in eng.items()} if idcg > 0 else {})
        return out

    pg, po = per_query_scores(gpt), per_query_scores(opus)
    engines = [e for e in set().union(*pg) if sum(1 for s in pg if e in s) >= minq]

    def agree(idx):
        sg = {e: [pg[i][e] for i in idx if e in pg[i]] for e in engines}
        so = {e: [po[i][e] for i in idx if e in po[i]] for e in engines}
        names = [e for e in engines if sg[e] and so[e]]
        if len(names) < 3:
            return None
        return spearman([sum(sg[e]) / len(sg[e]) for e in names], [sum(so[e]) / len(so[e]) for e in names])

    point = agree(range(len(queries)))
    boots = sorted(v for v in (agree([rng.randrange(len(queries)) for _ in queries]) for _ in range(2000)) if v is not None)
    print(f"{sample_dir}: engine-level Spearman {point:.3f}, query-cluster bootstrap 95% CI {boots[int(0.025*len(boots))]:.2f}..{boots[int(0.975*len(boots))]:.2f}")


run(sys.argv[1], 6)
run(sys.argv[2], 4)
