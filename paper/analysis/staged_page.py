import glob
import json
import random
import sys
from collections import defaultdict

raters_dir, staged_dir, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
rng = random.Random(11)
key = {str(x["id"]): x for x in json.load(open(raters_dir + "/items_key.json"))}


def load(pattern, field):
    out = {}
    for f in sorted(glob.glob(pattern)):
        for row in json.load(open(f)):
            out[str(row["id"])] = int(row[field])
    return out


snipA, pageA = load(raters_dir + "/labels_A_part*.json", "snippet_grade"), load(raters_dir + "/labels_A_part*.json", "page_grade")
snipB, pageB = load(raters_dir + "/labels_B_part*.json", "snippet_grade"), load(raters_dir + "/labels_B_part*.json", "page_grade")
staged = load(staged_dir + "/labels_S_part*.json", "grade")
ids = sorted(staged)
groups = defaultdict(list)
for i in ids:
    groups[(key[i]["run"], key[i]["query"])].append(i)
qkeys = list(groups)


def kappa_q(xs, ys):
    n = len(xs)
    k = 5
    obs = [[0] * k for _ in range(k)]
    for x, y in zip(xs, ys):
        obs[x][y] += 1
    rx = [sum(r) for r in obs]
    cy = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    num = sum(((i - j) ** 2) * obs[i][j] for i in range(k) for j in range(k))
    den = sum(((i - j) ** 2) * rx[i] * cy[j] / n for i in range(k) for j in range(k))
    return 1 - num / den if den else float("nan")


def stats(sel):
    def changed(a, b):
        return sum(a[i] != b[i] for i in sel) / len(sel)

    def shift(a, b):
        return sum(b[i] - a[i] for i in sel) / len(sel)

    judge = {i: key[i]["judge_rating"] for i in sel}
    return {
        "n": len(sel),
        "staged_changed_A": changed(staged, pageA), "staged_changed_B": changed(staged, pageB),
        "staged_shift_A": shift(staged, pageA), "staged_shift_B": shift(staged, pageB),
        "inprompt_changed_A": changed(snipA, pageA), "inprompt_changed_B": changed(snipB, pageB),
        "inprompt_shift_A": shift(snipA, pageA), "inprompt_shift_B": shift(snipB, pageB),
        "kappa_staged_vs_inpromptA": kappa_q([staged[i] for i in sel], [snipA[i] for i in sel]),
        "kappa_staged_vs_inpromptB": kappa_q([staged[i] for i in sel], [snipB[i] for i in sel]),
        "kappa_staged_vs_pageA": kappa_q([staged[i] for i in sel], [pageA[i] for i in sel]),
        "kappa_judge_vs_staged": kappa_q([judge[i] for i in sel], [staged[i] for i in sel]),
        "kappa_judge_vs_inpromptA": kappa_q([judge[i] for i in sel], [snipA[i] for i in sel]),
        "kappa_judge_vs_pageA": kappa_q([judge[i] for i in sel], [pageA[i] for i in sel]),
        "within1_judge_staged": sum(abs(judge[i] - staged[i]) <= 1 for i in sel) / len(sel),
        "mean_staged": sum(staged[i] for i in sel) / len(sel), "mean_judge": sum(judge[i] for i in sel) / len(sel),
        "mean_pageA": sum(pageA[i] for i in sel) / len(sel), "mean_inpromptA": sum(snipA[i] for i in sel) / len(sel),
        "up_A": sum(pageA[i] > staged[i] for i in sel), "down_A": sum(pageA[i] < staged[i] for i in sel),
    }


def ci(fn, qk, b=1000):
    vals = []
    for _ in range(b):
        samp = [qk[rng.randrange(len(qk))] for _ in qk]
        sel = [i for q in samp for i in groups[q]]
        vals.append(fn(sel))
    vals.sort()
    return vals[int(.025 * b)], vals[int(.975 * b)]


res = {}
for name, pred in (("all", lambda i: True), ("news", lambda i: key[i]["bench"] == "news"), ("agentic_rare", lambda i: key[i]["bench"] == "agentic_rare")):
    sel = [i for i in ids if pred(i)]
    qk = [q for q in qkeys if pred(groups[q][0])]
    s = stats(sel)
    s["ci_staged_changed_A"] = ci(lambda x: stats(x)["staged_changed_A"], qk, 400)
    s["ci_staged_shift_A"] = ci(lambda x: stats(x)["staged_shift_A"], qk, 400)
    s["ci_kappa_judge_vs_staged"] = ci(lambda x: stats(x)["kappa_judge_vs_staged"], qk, 400)
    s["ci_kappa_staged_vs_inpromptA"] = ci(lambda x: stats(x)["kappa_staged_vs_inpromptA"], qk, 400)
    res[name] = s
    print(name, json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.items()}, default=lambda v: [round(x, 3) for x in v]))
json.dump(res, open(out_path, "w"), indent=1)
