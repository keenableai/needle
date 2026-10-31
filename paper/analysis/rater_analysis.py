import collections
import glob
import json
import os
import random
import sys

items_path, raters_dir, out_json = sys.argv[1], sys.argv[2], sys.argv[3]
rng = random.Random(9)
items = {it["id"]: it for it in json.load(open(items_path))}


def load_rater(name):
    labels = {}
    for p in sorted(glob.glob(os.path.join(raters_dir, f"labels_{name}_part*.json"))):
        for rec in json.load(open(p)):
            labels[int(rec["id"])] = rec
    return labels


A, B = load_rater("A"), load_rater("B")
ids = sorted(i for i in items if i in A and i in B and items[i]["judge_rating"] is not None)
print("items labeled by both", len(ids), "of", len(items), "A", len(A), "B", len(B))


def qkappa(x, y, k=5):
    n = len(x)
    o = [[0] * k for _ in range(k)]
    for a, b in zip(x, y):
        o[a][b] += 1
    rx = [sum(o[i]) for i in range(k)]
    ry = [sum(o[i][j] for i in range(k)) for j in range(k)]
    num = sum(((i - j) ** 2) * o[i][j] for i in range(k) for j in range(k))
    den = sum(((i - j) ** 2) * rx[i] * ry[j] / n for i in range(k) for j in range(k))
    return 1 - num / den if den else float("nan")


def rank(v):
    s = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and v[s[j + 1]] == v[s[i]]:
            j += 1
        for t in range(i, j + 1):
            r[s[t]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(x, y):
    rx, ry = rank(x), rank(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx) ** 0.5
    vy = sum((b - my) ** 2 for b in ry) ** 0.5
    return cov / (vx * vy) if vx and vy else float("nan")


def agree(x, y):
    n = len(x)
    return {"n": n, "exact": sum(a == b for a, b in zip(x, y)) / n, "within1": sum(abs(a - b) <= 1 for a, b in zip(x, y)) / n, "kappa_q": qkappa(x, y), "spearman": spearman(x, y), "mean_x": sum(x) / n, "mean_y": sum(y) / n}


def boot_kappa(x, y, groups, n=1000):
    by_g = collections.defaultdict(list)
    for i, g in enumerate(groups):
        by_g[g].append(i)
    clusters = list(by_g.values())
    ks = []
    for _ in range(n):
        idx = [i for _ in clusters for i in clusters[rng.randrange(len(clusters))]]
        ks.append(qkappa([x[i] for i in idx], [y[i] for i in idx]))
    ks.sort()
    return ks[int(0.025 * n)], ks[int(0.975 * n)]


def g(rec, key):
    return max(0, min(4, int(rec[key])))


results = {}
for bench in ("news", "agentic_rare", "all"):
    sel = [i for i in ids if bench == "all" or items[i]["bench"] == bench]
    judge = [int(items[i]["judge_rating"]) for i in sel]
    a_page = [g(A[i], "page_grade") for i in sel]
    b_page = [g(B[i], "page_grade") for i in sel]
    a_snip = [g(A[i], "snippet_grade") for i in sel]
    b_snip = [g(B[i], "snippet_grade") for i in sel]
    cons = [round((a + b) / 2 + 1e-9) for a, b in zip(a_page, b_page)]
    cons_snip = [round((a + b) / 2 + 1e-9) for a, b in zip(a_snip, b_snip)]
    missing = sum(1 for i in sel if A[i].get("page_missing") or B[i].get("page_missing"))
    r = {
        "n": len(sel), "page_missing_either": missing,
        "A_vs_B_page": agree(a_page, b_page), "A_vs_B_snippet": agree(a_snip, b_snip),
        "judge_vs_A_page": agree(judge, a_page), "judge_vs_B_page": agree(judge, b_page),
        "judge_vs_A_snippet": agree(judge, a_snip), "judge_vs_B_snippet": agree(judge, b_snip),
        "judge_vs_consensus_page": agree(judge, cons), "judge_vs_consensus_snippet": agree(judge, cons_snip),
        "snippet_to_page_shift": {
            "A_mean": sum(p - s for p, s in zip(a_page, a_snip)) / len(sel),
            "B_mean": sum(p - s for p, s in zip(b_page, b_snip)) / len(sel),
            "A_changed": sum(p != s for p, s in zip(a_page, a_snip)) / len(sel),
            "B_changed": sum(p != s for p, s in zip(b_page, b_snip)) / len(sel),
            "A_up": sum(p > s for p, s in zip(a_page, a_snip)) / len(sel),
            "A_down": sum(p < s for p, s in zip(a_page, a_snip)) / len(sel),
            "B_up": sum(p > s for p, s in zip(b_page, b_snip)) / len(sel),
            "B_down": sum(p < s for p, s in zip(b_page, b_snip)) / len(sel),
        },
        "ci_kappa_A_vs_B_page": boot_kappa(a_page, b_page, [items[i]["query"] for i in sel]),
        "ci_kappa_judge_vs_consensus_page": boot_kappa(judge, cons, [items[i]["query"] for i in sel]),
        "judge_dist": collections.Counter(judge), "consensus_dist": collections.Counter(cons),
    }
    quoted = [i for i in sel if items[i]["query"].count('"') >= 2]
    plain = [i for i in sel if i not in set(quoted)]
    r["quoted_queries"] = {"items": len(quoted), "queries": len({items[i]["query"] for i in quoted}),
                           "wrapped": len({items[i]["query"] for i in quoted if items[i]["query"].strip().lower().startswith("query:")}),
                           "consensus_zero_share": sum(1 for i, c in zip(sel, cons) if i in set(quoted) and c == 0) / max(1, len(quoted)),
                           "judge_zero_share": sum(1 for i, j in zip(sel, judge) if i in set(quoted) and j == 0) / max(1, len(quoted))}
    if plain:
        pj = [int(items[i]["judge_rating"]) for i in plain]
        pa = [g(A[i], "page_grade") for i in plain]
        pb = [g(B[i], "page_grade") for i in plain]
        pc = [round((a + b) / 2 + 1e-9) for a, b in zip(pa, pb)]
        r["unquoted_only"] = {"n": len(plain), "A_vs_B_page": agree(pa, pb), "judge_vs_consensus_page": agree(pj, pc)}
    per_eng = collections.defaultdict(lambda: [[], []])
    for i, j, c in zip(sel, judge, cons):
        for e, _rank in items[i]["engines"]:
            per_eng[e][0].append(j)
            per_eng[e][1].append(c)
    eng_rows = {e: (len(v[0]), sum(v[0]) / len(v[0]), sum(v[1]) / len(v[1])) for e, v in per_eng.items() if len(v[0]) >= 20}
    names = sorted(eng_rows)
    r["engine_level"] = {"engines": len(names), "spearman_judge_vs_consensus": spearman([eng_rows[e][1] for e in names], [eng_rows[e][2] for e in names]), "rows": eng_rows}
    results[bench] = r

json.dump(results, open(out_json, "w"), indent=1, default=str)
for bench, r in results.items():
    print(f"== {bench}: n={r['n']} page_missing_either={r['page_missing_either']}")
    for k in ("A_vs_B_page", "A_vs_B_snippet", "judge_vs_A_page", "judge_vs_B_page", "judge_vs_A_snippet", "judge_vs_B_snippet", "judge_vs_consensus_page", "judge_vs_consensus_snippet"):
        a = r[k]
        print(f"  {k:28s} exact {a['exact']:.3f} within1 {a['within1']:.3f} kappa_q {a['kappa_q']:.3f} spearman {a['spearman']:.3f} means {a['mean_x']:.2f}/{a['mean_y']:.2f}")
    print("  shift", {k: round(v, 3) for k, v in r["snippet_to_page_shift"].items()})
    print("  CI kappa A-B page", [round(v, 3) for v in r["ci_kappa_A_vs_B_page"]], "CI kappa judge-consensus", [round(v, 3) for v in r["ci_kappa_judge_vs_consensus_page"]])
    print("  quoted", r["quoted_queries"], "unquoted", {k: (round(v["kappa_q"], 3) if isinstance(v, dict) else v) for k, v in r.get("unquoted_only", {}).items()})
    print("  engine-level spearman", round(r["engine_level"]["spearman_judge_vs_consensus"], 3), "engines", r["engine_level"]["engines"])
