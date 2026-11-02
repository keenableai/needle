import collections
import glob
import json
import os
import random
import sys

from common import ci

rng = random.Random(4)


def qkappa(x, y, k=5):
    n = len(x)
    o = [[0] * k for _ in range(k)]
    for a, b in zip(x, y, strict=True):
        o[a][b] += 1
    rx = [sum(o[i]) for i in range(k)]
    ry = [sum(o[i][j] for i in range(k)) for j in range(k)]
    num = sum(((i - j) ** 2) * o[i][j] for i in range(k) for j in range(k))
    den = sum(((i - j) ** 2) * rx[i] * ry[j] / n for i in range(k) for j in range(k))
    return 1 - num / den if den else float("nan")


def agree(x, y, groups):
    n = len(x)
    by_g = collections.defaultdict(list)
    for i, g in enumerate(groups):
        by_g[g].append(i)
    clusters = list(by_g.values())
    ks = []
    for _ in range(1000):
        idx = [i for _ in clusters for i in clusters[rng.randrange(len(clusters))]]
        ks.append(qkappa([x[i] for i in idx], [y[i] for i in idx]))
    return {"n": n, "exact": sum(a == b for a, b in zip(x, y, strict=True)) / n, "within1": sum(abs(a - b) <= 1 for a, b in zip(x, y, strict=True)) / n,
            "kappa_q": qkappa(x, y), "kappa_ci": ci(ks), "mean_x": sum(x) / n, "mean_y": sum(y) / n}


out = {}
for bench, site_dir, rej_path in (("news", sys.argv[1], sys.argv[3]), ("rare", sys.argv[2], sys.argv[4])):
    key = json.load(open(os.path.join(site_dir, "key.json")))
    claude = {}
    for p in glob.glob(os.path.join(site_dir, "labels_part*.json")):
        for rec in json.load(open(p)):
            claude[str(rec["id"])] = int(rec["rating"])
    rej = json.load(open(rej_path)) if os.path.exists(rej_path) else {}
    ids = [i for i in key if i in claude and rej.get(i, {}).get("rating") is not None]
    g_date = [int(key[i]["gpt"]) for i in ids]
    g_nodate = [int(rej[i]["rating"]) for i in ids]
    cl = [claude[i] for i in ids]
    q = [key[i]["q"] for i in ids]
    print(f"== {bench}: items {len(ids)} (key {len(key)}, claude {len(claude)}, rejudged {sum(1 for r in rej.values() if r.get('rating') is not None)}, errors {sum(1 for r in rej.values() if r.get('error'))})")
    if not ids:
        continue
    out[bench] = {"dates_vs_nodates": agree(g_date, g_nodate, q), "nodates_vs_claude": agree(g_nodate, cl, q), "dates_vs_claude": agree(g_date, cl, q)}
    print("  GPT with dates vs GPT without dates:", out[bench]["dates_vs_nodates"])
    print("  GPT without dates vs Claude:        ", out[bench]["nodates_vs_claude"])
    print("  GPT with dates vs Claude:           ", out[bench]["dates_vs_claude"])
json.dump(out, open(sys.argv[5], "w"), indent=1)
