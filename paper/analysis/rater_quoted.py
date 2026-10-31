import glob
import json
import sys

R = sys.argv[1]
items = {it["id"]: it for it in json.load(open(f"{R}/items_key.json"))}


def load(n):
    d = {}
    for p in glob.glob(f"{R}/labels_{n}_part*.json"):
        for r in json.load(open(p)):
            d[int(r["id"])] = r
    return d


A, B = load("A"), load("B")


def qk(x, y, k=5):
    n = len(x)
    o = [[0] * k for _ in range(k)]
    for a, b in zip(x, y):
        o[a][b] += 1
    rx = [sum(o[i]) for i in range(k)]
    ry = [sum(o[i][j] for i in range(k)) for j in range(k)]
    num = sum((i - j) ** 2 * o[i][j] for i in range(k) for j in range(k))
    den = sum((i - j) ** 2 * rx[i] * ry[j] / n for i in range(k) for j in range(k))
    return 1 - num / den if den else float("nan")


for bench in ("agentic_rare", "news"):
    for name, cond in (("quoted", lambda q: q.count('"') >= 2), ("unquoted", lambda q: q.count('"') < 2)):
        ids = [i for i in items if items[i]["bench"] == bench and cond(items[i]["query"]) and items[i]["judge_rating"] is not None]
        if not ids:
            continue
        j = [int(items[i]["judge_rating"]) for i in ids]
        c = [round((A[i]["page_grade"] + B[i]["page_grade"]) / 2 + 1e-9) for i in ids]
        ab = qk([A[i]["page_grade"] for i in ids], [B[i]["page_grade"] for i in ids])
        print(bench, name, "n", len(ids), "queries", len({items[i]["query"] for i in ids}), "judge-consensus k %.3f" % qk(j, c), "A-B k %.3f" % ab,
              "exact %.2f" % (sum(a == b for a, b in zip(j, c)) / len(ids)), "judge0 %.2f cons0 %.2f" % (sum(x == 0 for x in j) / len(j), sum(x == 0 for x in c) / len(c)))
