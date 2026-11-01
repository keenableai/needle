import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from needle.shared.metrics import apply_redundancy_penalties, dcg_at_k, normalize_url

full_dir, trunc_dir = Path(sys.argv[1]), Path(sys.argv[2])
key = {int(k): v for k, v in json.load(open(full_dir / "key.json")).items()}
queries = json.load(open(full_dir / "queries.json"))


def load(d):
    out = {}
    for f in sorted(d.glob("labels_part*.json")):
        for row in json.load(open(f)):
            out[int(row["id"])] = int(row["rating"])
    return out


opus = load(full_dir)
trunc = load(trunc_dir)
gpt = {i: key[i]["gpt"] for i in key}
ids = sorted(set(opus) & set(trunc))
n = len(ids)
print("n", n)


def kappa_quad(a, b):
    obs = Counter(zip(a, b)); pa, pb = Counter(a), Counter(b)
    num = sum((i - j) ** 2 * obs[(i, j)] for i in range(5) for j in range(5))
    den = sum((i - j) ** 2 * pa[i] * pb[j] / len(a) for i in range(5) for j in range(5))
    return 1 - num / den


def item_stats(x, y, label):
    a = [x[i] for i in ids]; b = [y[i] for i in ids]
    exact = sum(p == q for p, q in zip(a, b)) / n
    w1 = sum(abs(p - q) <= 1 for p, q in zip(a, b)) / n
    print(f"{label}: exact={exact:.3f} within1={w1:.3f} kappa_quad={kappa_quad(a, b):.3f} mean_x={sum(a)/n:.2f} mean_y={sum(b)/n:.2f}")


item_stats(opus, trunc, "opus full vs opus 200")
item_stats(gpt, trunc, "gpt full vs opus 200")
def engine_scores(rating_of):
    per = defaultdict(list)
    for q in queries:
        pool = {}; eng = {}
        for name, m in q["engines"].items():
            if any(i not in rating_of for i in m["positions"]):
                continue
            urls = [key[i]["url"] for i in m["positions"]]
            rs = [rating_of[i] for i in m["positions"]]
            for u, r in zip(urls, rs):
                pool[normalize_url(u)] = max(pool.get(normalize_url(u), 0), r)
            eng[name] = apply_redundancy_penalties(urls, rs, query_text=q["query"])
        idcg = dcg_at_k(sorted(pool.values(), reverse=True))
        if idcg <= 0:
            continue
        for name, rs in eng.items():
            per[name].append(dcg_at_k(rs) / idcg)
    return {k: sum(v) / len(v) for k, v in per.items() if len(v) >= 6}


def tau_b(a, b):
    n = len(a); c = d = ta = tb = 0
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


def spearman(a, b):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i]); r = [0.0] * len(v)
        for pos, i in enumerate(order):
            r[i] = pos
        return r
    ra, rb = ranks(a), ranks(b); ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    return sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / (sum((x - ma) ** 2 for x in ra) ** 0.5 * sum((y - mb) ** 2 for y in rb) ** 0.5)


so, st, sg = engine_scores(opus), engine_scores(trunc), engine_scores(gpt)
names = sorted(set(so) & set(st) & set(sg), key=lambda k: -sg[k])
for label, x, y in (("opus full vs opus 200", so, st), ("gpt vs opus 200", sg, st), ("gpt vs opus full", sg, so)):
    a = [x[k] for k in names]; b = [y[k] for k in names]
    print(f"engine-level {label}: tau_b={tau_b(a, b):.3f} spearman={spearman(a, b):.3f} mean|d|={sum(abs(p - q) for p, q in zip(a, b))/len(a):.3f} max|d|={max(abs(p - q) for p, q in zip(a, b)):.3f}")
snip = defaultdict(list)
for k in names:
    print(f"{k:20s} gpt={sg[k]:.3f} opus={so[k]:.3f} opus200={st[k]:.3f} d200={st[k]-so[k]:+.3f}")
