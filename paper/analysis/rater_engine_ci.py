import collections
import glob
import json
import random
import sys

R = sys.argv[1]
rng = random.Random(5)
items = {it["id"]: it for it in json.load(open(f"{R}/items_key.json"))}


def load(n):
    d = {}
    for p in glob.glob(f"{R}/labels_{n}_part*.json"):
        for r in json.load(open(p)):
            d[int(r["id"])] = r
    return d


A, B = load("A"), load("B")


def spearman(x, y):
    def rk(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(s):
            j = i
            while j + 1 < len(s) and v[s[j + 1]] == v[s[i]]:
                j += 1
            for t in range(i, j + 1):
                r[s[t]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = rk(x), rk(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx) ** 0.5
    vy = sum((b - my) ** 2 for b in ry) ** 0.5
    return cov / (vx * vy) if vx and vy else float("nan")


def engine_rho(ids):
    per = collections.defaultdict(lambda: [[], []])
    for i in ids:
        it = items[i]
        c = round((A[i]["page_grade"] + B[i]["page_grade"]) / 2 + 1e-9)
        for e, _ in it["engines"]:
            per[e][0].append(int(it["judge_rating"]))
            per[e][1].append(c)
    names = [e for e, v in per.items() if len(v[0]) >= 20]
    return spearman([sum(per[e][0]) / len(per[e][0]) for e in names], [sum(per[e][1]) / len(per[e][1]) for e in names]), len(names)


for bench in ("news", "agentic_rare", "all"):
    ids = [i for i in items if (bench == "all" or items[i]["bench"] == bench) and items[i]["judge_rating"] is not None]
    byq = collections.defaultdict(list)
    for i in ids:
        byq[items[i]["query"]].append(i)
    qs = list(byq.values())
    point, n_eng = engine_rho(ids)
    boots = []
    for _ in range(1000):
        samp = [i for _k in range(len(qs)) for i in qs[rng.randrange(len(qs))]]
        boots.append(engine_rho(samp)[0])
    boots.sort()
    per_eng = collections.Counter(e for i in ids for e, _ in items[i]["engines"])
    print(f"{bench}: engines {n_eng} spearman {point:.3f} query-bootstrap 95% [{boots[25]:.3f}, {boots[974]:.3f}] items per engine median {sorted(per_eng.values())[len(per_eng)//2]} min {min(per_eng.values())}")
