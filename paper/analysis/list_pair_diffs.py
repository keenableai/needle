import collections
import glob
import json
import math
import random
import sys

from needle.shared.metrics import normalize_url

L, out_path = sys.argv[1], sys.argv[2]
rng = random.Random(21)
GAIN = {4: 1.0, 3: 0.667, 2: 0.117, 1: 0.0, 0: 0.0}
items = {it["id"]: it for it in json.load(open(f"{L}/items_key.json"))}
lists = json.load(open(f"{L}/lists.json"))
labels = {}
for p in glob.glob(sys.argv[3] if len(sys.argv) > 3 else f"{L}/labels_L_part*.json"):
    for r in json.load(open(p)):
        labels[int(r["id"])] = int(r["grade"])
by_url = {(it["query"], it["url"]): it["id"] for it in items.values()}


def dcg(gs):
    return sum(GAIN.get(g, 0.0) / math.log2(i + 2) for i, g in enumerate(gs[:5]))


def grades(lst, which):
    per, pool = {}, {}
    for e, urls in lst["engines"].items():
        gs, seen = [], set()
        for u in urls:
            i = by_url.get((lst["query"], u))
            g = 0
            if i is not None:
                g = labels.get(i, 0) if which == "rater" else int(items[i].get("judge_rating") or 0)
            k = normalize_url(u)
            pool[k] = max(pool.get(k, 0), g)
            gs.append(0 if k in seen else g)
            seen.add(k)
        per[e] = dcg(gs)
    ideal = dcg(sorted(pool.values(), reverse=True))
    return {e: v / ideal for e, v in per.items()} if ideal > 0 else None


pre = {which: [grades(l, which) for l in lists] for which in ("judge", "rater")}
PAIRS = [("keenable", "exa"), ("exa", "perplexity"), ("keenable", "parallel"), ("keenable", "claude-search"), ("brave-llmcontext", "linkup"),
         ("you", "claude-search"), ("claude-search", "chatgpt-search"), ("bing", "tinyfish"), ("tinyfish", "ceramic"), ("keenable", "ceramic")]


def share_diff(idx, which, a, b):
    da = [pre[which][i][a] for i in idx if pre[which][i]]
    db = [pre[which][i][b] for i in idx if pre[which][i]]
    return sum(da) / len(da) - sum(db) / len(db)


n = len(lists)
res = {}
print(f"{'pair':32s} {'judge':>14s} {'rater':>14s}")
for a, b in PAIRS:
    idx = list(range(n))
    pj, pr = share_diff(idx, "judge", a, b), share_diff(idx, "rater", a, b)
    bj, br = [], []
    for _ in range(1000):
        samp = [rng.randrange(n) for _ in range(n)]
        bj.append(share_diff(samp, "judge", a, b))
        br.append(share_diff(samp, "rater", a, b))
    bj.sort(); br.sort()
    res[f"{a}|{b}"] = {"judge": pj, "judge_ci": (bj[25], bj[974]), "rater": pr, "rater_ci": (br[25], br[974])}
    print(f"{a+'-'+b:32s} {100*pj:+5.1f} [{100*bj[25]:+5.1f},{100*bj[974]:+5.1f}]  {100*pr:+5.1f} [{100*br[25]:+5.1f},{100*br[974]:+5.1f}]")
json.dump(res, open(out_path, "w"), indent=1)
