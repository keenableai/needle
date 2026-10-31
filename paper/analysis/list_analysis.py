import collections
import glob
import json
import math
import random
import sys

from needle.shared.metrics import normalize_url

L = sys.argv[1]
out_path = sys.argv[2]
rng = random.Random(8)
GAIN = {4: 1.0, 3: 0.667, 2: 0.117, 1: 0.0, 0: 0.0}
items = {it["id"]: it for it in json.load(open(f"{L}/items_key.json"))}
lists = json.load(open(f"{L}/lists.json"))
labels = {}
for p in glob.glob(sys.argv[3] if len(sys.argv) > 3 else f"{L}/labels_L_part*.json"):
    for r in json.load(open(p)):
        labels[int(r["id"])] = int(r["grade"])
by_url = {}
for it in items.values():
    by_url[(it["query"], it["url"])] = it["id"]
print("items", len(items), "rated", len(labels))


def dcg(gs):
    return sum(GAIN.get(g, 0.0) / math.log2(i + 2) for i, g in enumerate(gs[:5]))


def list_ndcg(lst, grade_of):
    per = {}
    pool = {}
    for e, urls in lst["engines"].items():
        gs, seen = [], set()
        for u in urls:
            g = grade_of(lst["query"], u)
            key = normalize_url(u)
            pool[key] = max(pool.get(key, 0), g)
            gs.append(0 if key in seen else g)
            seen.add(key)
        per[e] = dcg(gs)
    ideal = dcg(sorted(pool.values(), reverse=True))
    return {e: (v / ideal if ideal > 0 else None) for e, v in per.items()}, ideal


def judge_grade(q, u):
    it = items.get(by_url.get((q, u)))
    return int(it["judge_rating"]) if it and it.get("judge_rating") is not None else 0


def rater_grade(q, u):
    i = by_url.get((q, u))
    return labels.get(i, 0) if i is not None else 0


def spearman(x, y):
    def rk(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for pos, i in enumerate(s):
            r[i] = pos
        return r
    rx, ry = rk(x), rk(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx) ** 0.5
    vy = sum((b - my) ** 2 for b in ry) ** 0.5
    return cov / (vx * vy)


def tau_b(a, b):
    c = d = 0
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            x = (a[i] - a[j]) * (b[i] - b[j])
            c += x > 0
            d += x < 0
    return (c - d) / (c + d) if c + d else float("nan")


def shares(sel, grade_of):
    acc = collections.defaultdict(list)
    for lst in sel:
        nd, ideal = list_ndcg(lst, grade_of)
        if ideal <= 0:
            continue
        for e, v in nd.items():
            if v is not None:
                acc[e].append(v)
    return {e: sum(v) / len(v) for e, v in acc.items()}


result = {}
for bench in ("news", "agentic_rare", "all"):
    sel = [l for l in lists if bench == "all" or l["bench"] == bench]
    sj, sr = shares(sel, judge_grade), shares(sel, rater_grade)
    names = sorted(e for e in sj if e in sr)
    rho = spearman([sj[e] for e in names], [sr[e] for e in names])
    tb = tau_b([sj[e] for e in names], [sr[e] for e in names])
    boots = []
    for _ in range(1000):
        samp = [sel[rng.randrange(len(sel))] for _ in sel]
        a, b = shares(samp, judge_grade), shares(samp, rater_grade)
        nm = [e for e in names if e in a and e in b]
        boots.append(spearman([a[e] for e in nm], [b[e] for e in nm]))
    boots.sort()
    oj = sorted(names, key=lambda e: -sj[e])
    orr = sorted(names, key=lambda e: -sr[e])
    mad = sum(abs(sj[e] - sr[e]) for e in names) / len(names)
    print(f"{bench}: queries {len(sel)} engines {len(names)} spearman {rho:.3f} [{boots[25]:.3f},{boots[974]:.3f}] tau_b {tb:.3f} mean|diff| {mad:.3f}")
    print("   judge order:", oj[:6], "...", oj[-3:])
    print("   rater order:", orr[:6], "...", orr[-3:])
    result[bench] = {"queries": len(sel), "spearman": rho, "ci": (boots[25], boots[974]), "tau_b": tb, "mean_abs_diff": mad, "judge_shares": sj, "rater_shares": sr}
rated = {i: g for i, g in labels.items() if items[i].get("judge_rating") is not None}
ex = sum(1 for i, g in rated.items() if items[i]["judge_rating"] == g) / len(rated)
w1 = sum(1 for i, g in rated.items() if abs(items[i]["judge_rating"] - g) <= 1) / len(rated)
print("item-level exact %.3f within1 %.3f mean judge %.2f rater %.2f" % (ex, w1, sum(items[i]["judge_rating"] for i in rated) / len(rated), sum(rated.values()) / len(rated)))
result["item_level"] = {"exact": ex, "within1": w1}
json.dump(result, open(out_path, "w"), indent=1)
