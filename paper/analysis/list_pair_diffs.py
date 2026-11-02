import glob
import json
import random
import sys

from common import ci

from needle.shared.metrics import apply_redundancy_penalties, dcg_at_k, normalize_url

L, out_path, labels_glob = sys.argv[1:4]
rng = random.Random(21)
items = {it["id"]: it for it in json.load(open(f"{L}/items_key.json"))}
lists = json.load(open(f"{L}/lists.json"))
labels = {}
for p in glob.glob(labels_glob):
    for r in json.load(open(p)):
        labels[int(r["id"])] = int(r["grade"])
by_url = {(it["query"], it["url"]): it["id"] for it in items.values()}


def grades(lst, which):
    per, pool = {}, {}
    for e, urls in lst["engines"].items():
        gs = []
        for u in urls:
            i = by_url.get((lst["query"], u))
            g = 0
            if i is not None:
                g = labels.get(i, 0) if which == "rater" else int(items[i].get("judge_rating") or 0)
            k = normalize_url(u)
            pool[k] = max(pool.get(k, 0), g)
            gs.append(g)
        per[e] = dcg_at_k(apply_redundancy_penalties(urls, gs, query_text=lst["query"]))
    ideal = dcg_at_k(sorted(pool.values(), reverse=True))
    return {e: v / ideal for e, v in per.items()} if ideal > 0 else None


pre = {which: [grades(lst, which) for lst in lists] for which in ("judge", "rater")}
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
    cj, cr = ci(bj), ci(br)
    res[f"{a}|{b}"] = {"judge": pj, "judge_ci": cj, "rater": pr, "rater_ci": cr}
    print(f"{a+'-'+b:32s} {100*pj:+5.1f} [{100*cj[0]:+5.1f},{100*cj[1]:+5.1f}]  {100*pr:+5.1f} [{100*cr[0]:+5.1f},{100*cr[1]:+5.1f}]")
json.dump(res, open(out_path, "w"), indent=1)
