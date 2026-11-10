import glob
import json
import sys

raters_dir, out_path = sys.argv[1:3]
key = {str(x["id"]): x for x in json.load(open(f"{raters_dir}/items_key.json"))}


def parts(tag):
    return {str(r["id"]): r for f in sorted(glob.glob(f"{raters_dir}/labels_{tag}_part*.json")) for r in json.load(open(f))}


def kappa(xs, ys, k=5):
    obs = [[0] * k for _ in range(k)]
    for x, y in zip(xs, ys, strict=True):
        obs[x][y] += 1
    rx = [sum(r) for r in obs]
    cy = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    num = sum((i - j) ** 2 * obs[i][j] for i in range(k) for j in range(k))
    den = sum((i - j) ** 2 * rx[i] * cy[j] / len(xs) for i in range(k) for j in range(k))
    return 1 - num / den


grades = {"A": parts("A"), "B": parts("B")}
for name in ("gemini", "grok"):
    grades[name] = {k: v for k, v in json.load(open(f"{raters_dir}/labels_{name}.json")).items() if "error" not in v}
ids = [i for i in key if all(i in g for g in grades.values()) and key[i]["judge_rating"] is not None]
g = {name: {i: max(0, min(4, int(v[i]["snippet_grade"]))) for i in ids} for name, v in grades.items()}
g["judge"] = {i: int(key[i]["judge_rating"]) for i in ids}
g["consensus"] = {i: round((g["A"][i] + g["B"][i]) / 2 + 1e-9) for i in ids}
pairs = [("A", "B"), ("judge", "consensus"), ("gemini", "consensus"), ("grok", "consensus"), ("gemini", "judge"), ("grok", "judge"), ("gemini", "grok")]
res = {}
for bench in ("news", "agentic_rare", "all"):
    sel = [i for i in ids if bench in ("all", key[i]["bench"])]
    res[bench] = {"n": len(sel), "mean": {n: sum(v[i] for i in sel) / len(sel) for n, v in g.items()}, "kappa": {f"{a}_vs_{b}": kappa([g[a][i] for i in sel], [g[b][i] for i in sel]) for a, b in pairs}}
    print(bench, len(sel), {k: round(v, 3) for k, v in res[bench]["kappa"].items()}, {k: round(v, 2) for k, v in res[bench]["mean"].items()})
json.dump(res, open(out_path, "w"), indent=1)
