import collections
import glob
import json
import os
import random
import re
import sys

site, out_dir, n_queries, per_query = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
rng = random.Random(7)
os.makedirs(out_dir, exist_ok=True)

KEEP = "keenable exa google bing brave brave-llmcontext parallel perplexity tavily linkup tinyfish octen ceramic you firecrawl kagi jina context deepseek claude-search chatgpt-search".split()
BENCHES = {"news": ("hfnews", "ndcg.json"), "agentic_rare": ("hfrare", "agentic_rare.json")}
LO, HI = "2026-10-17", "2026-10-30"


def norm_url(u):
    u = u.strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    u = u.split("#", 1)[0].rstrip("/")
    return u


items = []
for bench, (folder, report) in BENCHES.items():
    runs = []
    for d in sorted(glob.glob(os.path.join(site, folder, "*"))):
        name = os.path.basename(d)
        if not (LO <= name[:10] < HI) or not os.path.exists(os.path.join(d, report)):
            continue
        rep = json.load(open(os.path.join(d, report)))
        have = [e for e in KEEP if e in rep["engines"] and os.path.exists(os.path.join(d, rep["engines"][e].get("per_query_path", "x")))]
        if len(have) >= 19:
            runs.append((d, rep, have))
    print(bench, "eligible runs", len(runs))
    cands = []
    for d, rep, have in runs:
        n = rep["num_queries"]
        cands.extend((d, rep, have, i) for i in range(n))
    rng.shuffle(cands)
    seen_q = set()
    picked = 0
    for d, rep, have, qi in cands:
        if picked >= n_queries:
            break
        per_engine = {}
        for e in have:
            per_engine[e] = json.load(open(os.path.join(d, rep["engines"][e]["per_query_path"])))["per_query"]
        q = per_engine[have[0]][qi]["query"]
        if q in seen_q:
            continue
        pool = collections.OrderedDict()
        for e in have:
            pq = per_engine[e][qi]
            if pq.get("search_error") is not None:
                continue
            for rank, r in enumerate(pq["results"][:5], 1):
                k = norm_url(r["url"])
                if k not in pool:
                    pool[k] = {"url": r["url"], "title": r.get("title"), "snippet": r.get("snippet"), "judge_rating": r.get("rating"), "judge_penalized": r.get("penalized"), "engines": []}
                pool[k]["engines"].append([e, rank])
        if len(pool) < 3:
            continue
        seen_q.add(q)
        picked += 1
        keys = list(pool)
        rng.shuffle(keys)
        for k in keys[:per_query]:
            it = pool[k]
            items.append({"id": len(items), "bench": bench, "run": os.path.basename(d), "today": os.path.basename(d)[:10], "query": q, "query_profile": per_engine[have[0]][qi].get("query_profile"), **it})
    print(bench, "queries picked", picked)

json.dump(items, open(os.path.join(out_dir, "items_key.json"), "w"), indent=1)
by_bench = collections.Counter(i["bench"] for i in items)
print("items", len(items), dict(by_bench), "unique urls", len({norm_url(i["url"]) for i in items}))
print("judge rating dist", collections.Counter(str(i["judge_rating"]) for i in items))
