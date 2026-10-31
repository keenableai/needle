import collections
import glob
import json
import random
import sys

raters_dir, out_path = sys.argv[1], sys.argv[2]
extra = sys.argv[3:]
rng = random.Random(3)
key = {str(x["id"]): x for x in json.load(open(f"{raters_dir}/items_key.json"))}


def load_parts(tag):
    out = {}
    for f in sorted(glob.glob(f"{raters_dir}/labels_{tag}_part*.json")):
        for row in json.load(open(f)):
            out[str(row["id"])] = row
    return out


A, B = load_parts("A"), load_parts("B")
R = {name: {k: v for k, v in json.load(open(f"{raters_dir}/labels_{name}.json")).items() if "error" not in v} for name in extra}
ids = [i for i in key if all(i in R[n] for n in R)]
groups = collections.defaultdict(list)
for i in ids:
    groups[(key[i]["run"], key[i]["query"])].append(i)
qkeys = list(groups)
consensus = {i: round((A[i]["page_grade"] + B[i]["page_grade"]) / 2 + 1e-9) for i in ids}
judge = {i: key[i]["judge_rating"] for i in ids}


def kappa_q(xs, ys):
    n, k = len(xs), 5
    obs = [[0] * k for _ in range(k)]
    for x, y in zip(xs, ys):
        obs[max(0, min(4, x))][max(0, min(4, y))] += 1
    rx = [sum(r) for r in obs]
    cy = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    num = sum(((i - j) ** 2) * obs[i][j] for i in range(k) for j in range(k))
    den = sum(((i - j) ** 2) * rx[i] * cy[j] / n for i in range(k) for j in range(k))
    return 1 - num / den if den else float("nan")


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
                r[order[t]] = (i + j) / 2 + 1
            i = j + 1
        return r
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return cov / (va * vb) if va and vb else float("nan")


def engine_means(grade, sel):
    acc = collections.defaultdict(list)
    for i in sel:
        for eng, _ in key[i]["engines"]:
            acc[eng].append(grade[i])
    return {e: sum(v) / len(v) for e, v in acc.items() if len(v) >= 10}


def stats(sel, name):
    g = {i: R[name][i]["page_grade"] for i in sel}
    s = {i: R[name][i]["snippet_grade"] for i in sel}
    em_j, em_r = engine_means(judge, sel), engine_means(g, sel)
    common = sorted(set(em_j) & set(em_r))
    return {
        "n": len(sel),
        "kappa_vs_consensus": kappa_q([g[i] for i in sel], [consensus[i] for i in sel]),
        "kappa_vs_A": kappa_q([g[i] for i in sel], [A[i]["page_grade"] for i in sel]),
        "kappa_vs_judge_page": kappa_q([g[i] for i in sel], [judge[i] for i in sel]),
        "kappa_snippet_vs_judge": kappa_q([s[i] for i in sel], [judge[i] for i in sel]),
        "within1_vs_judge": sum(abs(g[i] - judge[i]) <= 1 for i in sel) / len(sel),
        "mean": sum(g[i] for i in sel) / len(sel),
        "spearman_engines_vs_judge": spearman([em_j[e] for e in common], [em_r[e] for e in common]),
        "spearman_engines_vs_consensus": spearman([engine_means(consensus, sel)[e] for e in common], [em_r[e] for e in common]),
        "engines": len(common),
    }


def ci(fn, qk, b=500):
    vals = []
    for _ in range(b):
        samp = [qk[rng.randrange(len(qk))] for _ in qk]
        vals.append(fn([i for q in samp for i in groups[q]]))
    vals.sort()
    return vals[int(.025 * b)], vals[int(.975 * b)]


res = {}
for name in R:
    res[name] = {}
    for bench, pred in (("all", lambda i: True), ("news", lambda i: key[i]["bench"] == "news"), ("agentic_rare", lambda i: key[i]["bench"] == "agentic_rare")):
        sel = [i for i in ids if pred(i)]
        qk = [q for q in qkeys if pred(groups[q][0])]
        st = stats(sel, name)
        st["ci_kappa_vs_judge_page"] = ci(lambda x: stats(x, name)["kappa_vs_judge_page"], qk)
        st["ci_kappa_vs_consensus"] = ci(lambda x: stats(x, name)["kappa_vs_consensus"], qk)
        st["ci_spearman_engines_vs_judge"] = ci(lambda x: stats(x, name)["spearman_engines_vs_judge"], qk, 300)
        res[name][bench] = st
        print(name, bench, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in st.items()}, flush=True)
if len(R) >= 2:
    names = list(R)
    for bench, pred in (("all", lambda i: True), ("news", lambda i: key[i]["bench"] == "news"), ("agentic_rare", lambda i: key[i]["bench"] == "agentic_rare")):
        sel = [i for i in ids if pred(i)]
        k = kappa_q([R[names[0]][i]["page_grade"] for i in sel], [R[names[1]][i]["page_grade"] for i in sel])
        res.setdefault("between", {})[bench] = k
        print("between", names, bench, round(k, 3))
json.dump(res, open(out_path, "w"), indent=1)
