import collections
import itertools
import json
import random
import sys

from common import pct

items_path, panel_dir, out_path = sys.argv[1:4]
MODELS = {"gpt-6-luna": "GPT-6 Luna", "claude-opus-5.5": "Claude Opus 5.5", "gemini-4-argon": "Gemini 4 Argon", "grok-4.7": "Grok 4.7"}
key = {str(x["id"]): x for x in json.load(open(items_path))}
raw = {m: json.load(open(f"{panel_dir}/{m}.json")) for m in MODELS}
ids = sorted(i for i in key if all(raw[m].get(i, {}).get("rating") is not None for m in MODELS))
g = {m: {i: raw[m][i]["rating"] for i in ids} for m in MODELS}
rng = random.Random(42)


def qwk(xs, ys, k=5):
    obs = [[0] * k for _ in range(k)]
    for x, y in zip(xs, ys, strict=True):
        obs[x][y] += 1
    rx = [sum(r) for r in obs]
    cy = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    num = sum((i - j) ** 2 * obs[i][j] for i in range(k) for j in range(k))
    den = sum((i - j) ** 2 * rx[i] * cy[j] / len(xs) for i in range(k) for j in range(k))
    return 1 - num / den


def ranks(v):
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for t in range(i, j + 1):
            r[order[t]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(a, b):
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    return cov / (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5


def kendall_b(a, b):
    conc = disc = ta = tb = 0
    for i, j in itertools.combinations(range(len(a)), 2):
        da, db = a[i] - a[j], b[i] - b[j]
        if da and db:
            if (da > 0) == (db > 0):
                conc += 1
            else:
                disc += 1
        elif da:
            tb += 1
        elif db:
            ta += 1
    return (conc - disc) / ((conc + disc + ta) * (conc + disc + tb)) ** 0.5


def loo(m, i):
    others = [g[o][i] for o in MODELS if o != m]
    return sum(others) / len(others)


def agree(xs, ys_exact, ys_rank):
    n = len(xs)
    return {
        "n": n, "qwk": qwk(xs, ys_exact), "spearman": spearman(xs, ys_rank), "kendall_b": kendall_b(xs, ys_rank),
        "exact": sum(x == y for x, y in zip(xs, ys_exact, strict=True)) / n,
        "within1": sum(abs(x - y) <= 1 for x, y in zip(xs, ys_exact, strict=True)) / n,
        "mae": sum(abs(x - y) for x, y in zip(xs, ys_rank, strict=True)) / n,
    }


def vs_consensus(m, sel):
    cons = [loo(m, i) for i in sel]
    return agree([g[m][i] for i in sel], [round(c + 1e-9) for c in cons], cons)


def qwk_ci(m, sel, reps=1000):
    by_q = collections.defaultdict(list)
    for i in sel:
        by_q[(key[i]["run"], key[i]["query"])].append(i)
    clusters = list(by_q.values())
    vals = []
    for _ in range(reps):
        samp = [i for _ in clusters for i in clusters[rng.randrange(len(clusters))]]
        vals.append(qwk([g[m][i] for i in samp], [round(loo(m, i) + 1e-9) for i in samp]))
    return pct(vals, 0.025), pct(vals, 0.975)


res = {"models": MODELS, "errors": {m: sum(1 for i in key if raw[m].get(i, {}).get("rating") is None) for m in MODELS}, "cost": {m: sum(r["cost"] for r in raw[m].values()) for m in MODELS}}
for bench in ("news", "agentic_rare", "all"):
    sel = [i for i in ids if bench in ("all", key[i]["bench"])]
    r = {"n": len(sel), "models": {}, "pairs": {}}
    for m in MODELS:
        st = vs_consensus(m, sel)
        st["qwk_ci"] = qwk_ci(m, sel)
        st["mean"] = sum(g[m][i] for i in sel) / len(sel)
        st["dist"] = [sum(g[m][i] == k for i in sel) for k in range(5)]
        r["models"][m] = st
    for a, b in itertools.combinations(MODELS, 2):
        r["pairs"][f"{a}|{b}"] = agree([g[a][i] for i in sel], [g[b][i] for i in sel], [g[b][i] for i in sel])
    stored = [key[i]["judge_rating"] for i in sel]
    r["rerun_vs_stored"] = agree([g["gpt-6-luna"][i] for i in sel], stored, stored)
    res[bench] = r
    print(f"== {bench} n={len(sel)}")
    for m, st in r["models"].items():
        print(f"  {m:16s} qwk {st['qwk']:.3f} [{st['qwk_ci'][0]:.3f},{st['qwk_ci'][1]:.3f}] rho {st['spearman']:.3f} tau {st['kendall_b']:.3f} exact {st['exact']:.2f} ±1 {st['within1']:.2f} mae {st['mae']:.3f} mean {st['mean']:.2f} {st['dist']}")
    for p, st in r["pairs"].items():
        print(f"  {p:32s} qwk {st['qwk']:.3f} rho {st['spearman']:.3f} exact {st['exact']:.2f}")
    print("  rerun vs stored", {k: round(v, 3) for k, v in r["rerun_vs_stored"].items()})
print("errors", res["errors"], "cost", {m: round(c, 2) for m, c in res["cost"].items()})
json.dump(res, open(out_path, "w"), indent=1)
