import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from needle.shared.metrics import apply_redundancy_penalties, dcg_at_k, normalize_url

sample_dir = Path(sys.argv[1])
MINQ = int(sys.argv[2]) if len(sys.argv) > 2 else 6
key = {int(k): v for k, v in json.load(open(sample_dir / "key.json")).items()}
queries = json.load(open(sample_dir / "queries.json"))
labels = {}
for f in sorted(sample_dir.glob("labels_part*.json")):
    for row in json.load(open(f)):
        labels[int(row["id"])] = int(row["rating"])
missing = sorted(set(key) - set(labels))
print("labeled", len(labels), "of", len(key), "missing", len(missing))
ids = [i for i in key if i in labels]
a = [key[i]["gpt"] for i in ids]
b = [labels[i] for i in ids]
n = len(ids)

exact = sum(x == y for x, y in zip(a, b)) / n
within1 = sum(abs(x - y) <= 1 for x, y in zip(a, b)) / n


def kappa(a, b, weight):
    cats = range(5)
    obs = Counter(zip(a, b))
    pa, pb = Counter(a), Counter(b)
    num = sum(weight(i, j) * obs[(i, j)] for i in cats for j in cats)
    den = sum(weight(i, j) * pa[i] * pb[j] / n for i in cats for j in cats)
    return 1 - num / den


kq = kappa(a, b, lambda i, j: (i - j) ** 2)
kl = kappa(a, b, lambda i, j: abs(i - j))
k0 = kappa(a, b, lambda i, j: float(i != j))


def binary_kappa(a, b, thr):
    x = [int(v >= thr) for v in a]
    y = [int(v >= thr) for v in b]
    po = sum(i == j for i, j in zip(x, y)) / n
    pe = (sum(x) * sum(y) + (n - sum(x)) * (n - sum(y))) / n / n
    return (po - pe) / (1 - pe), po


def spearman(a, b):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for t in range(i, j + 1):
                r[order[t]] = (i + j) / 2
            i = j + 1
        return r
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    return cov / (sum((x - ma) ** 2 for x in ra) ** 0.5 * sum((y - mb) ** 2 for y in rb) ** 0.5)


print(f"n={n} exact={exact:.3f} within1={within1:.3f} kappa_quad={kq:.3f} kappa_lin={kl:.3f} kappa_unw={k0:.3f} spearman={spearman(a, b):.3f}")
for thr in (2, 3, 4):
    k, po = binary_kappa(a, b, thr)
    print(f"binary >= {thr}: kappa={k:.3f} agreement={po:.3f}")
print("mean rating gpt", sum(a) / n, "opus", sum(b) / n)
conf = Counter(zip(a, b))
print("confusion (gpt rows, opus cols)")
for i in range(5):
    print(i, [conf[(i, j)] for j in range(5)])

def engine_scores(rating_of):
    per_engine = defaultdict(list)
    for q in queries:
        pool = {}
        eng_ratings = {}
        for name, m in q["engines"].items():
            if any(i not in rating_of for i in m["positions"]):
                continue
            urls = [key[i]["url"] for i in m["positions"]]
            rs = [rating_of[i] for i in m["positions"]]
            for u, r in zip(urls, rs):
                pool[normalize_url(u)] = max(pool.get(normalize_url(u), 0), r)
            eng_ratings[name] = apply_redundancy_penalties(urls, rs, query_text=q["query"])
        idcg = dcg_at_k(sorted(pool.values(), reverse=True))
        if idcg <= 0:
            continue
        for name, rs in eng_ratings.items():
            per_engine[name].append(dcg_at_k(rs) / idcg)
    return {k: sum(v) / len(v) for k, v in per_engine.items() if len(v) >= MINQ}


gpt_rating = {i: key[i]["gpt"] for i in key}
sg = engine_scores(gpt_rating)
so = engine_scores(labels)
names = sorted(set(sg) & set(so), key=lambda k: -sg[k])


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


print("engines", len(names))
for k in names:
    print(f"{k:20s} gpt={sg[k]:.3f} opus={so[k]:.3f} d={so[k]-sg[k]:+.3f}")
print("engine-level tau_b", round(tau_b([sg[k] for k in names], [so[k] for k in names]), 3), "spearman", round(spearman([sg[k] for k in names], [so[k] for k in names]), 3))
print("mean abs share diff", round(sum(abs(so[k] - sg[k]) for k in names) / len(names), 3))
json.dump({"n": n, "exact": exact, "within1": within1, "kappa_quad": kq, "kappa_lin": kl, "engines": {k: [sg[k], so[k]] for k in names}}, open(sample_dir / "agreement.json", "w"), indent=1)
