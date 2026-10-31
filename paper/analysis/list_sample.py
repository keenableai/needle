import glob
import json
import os
import random
import sys

site, pairs_json, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
KEEP = "keenable exa google bing brave brave-llmcontext parallel perplexity tavily linkup tinyfish octen ceramic you firecrawl kagi jina context deepseek claude-search chatgpt-search".split()
table_runs = {ts.replace(":", "") for ts in json.load(open(pairs_json))["runs"]}
rng = random.Random(2026)
os.makedirs(out_dir, exist_ok=True)

items, lists = [], []
for bench, folder, report in (("news", "hfnews", "ndcg.json"), ("agentic_rare", "hfrare", "agentic_rare.json")):
    cands = []
    for d in sorted(glob.glob(os.path.join(site, folder, "*"))):
        name = os.path.basename(d)
        if name not in table_runs or not os.path.exists(os.path.join(d, report)):
            continue
        rep = json.load(open(os.path.join(d, report)))
        pqs = {}
        for e in KEEP:
            p = os.path.join(d, rep["engines"].get(e, {}).get("per_query_path", ""))
            if os.path.isfile(p):
                pqs[e] = json.load(open(p))["per_query"]
        if len(pqs) < 21:
            continue
        for qi in range(len(pqs["keenable"])):
            if any(pqs[e][qi].get("search_error") for e in KEEP):
                continue
            if all(not pqs[e][qi].get("results") for e in KEEP):
                continue
            cands.append((name, qi, pqs))
    rng.shuffle(cands)
    for name, qi, pqs in cands[:10]:
        q = pqs["keenable"][qi]["query"]
        today = name[:10]
        seen = {}
        per_engine = {}
        for e in KEEP:
            urls = []
            for r in (pqs[e][qi].get("results") or [])[:5]:
                u = r["url"]
                if u not in seen:
                    seen[u] = {"id": len(items) + len(seen), "today": today, "query": q, "url": u, "title": r.get("title") or "", "snippet": (r.get("snippet") or "")[:2000],
                               "judge_rating": r.get("rating"), "bench": bench}
                urls.append(u)
            per_engine[e] = urls
        base = len(items)
        for u, it in seen.items():
            it["id"] = base + list(seen).index(u)
            items.append(it)
        lists.append({"bench": bench, "run": name, "qi": qi, "query": q, "today": today, "engines": per_engine, "penalized": {e: pqs[e][qi].get("penalized_ratings") for e in KEEP}, "ndcg": {e: pqs[e][qi].get("ndcg") for e in KEEP}})

json.dump(items, open(os.path.join(out_dir, "items_key.json"), "w"))
json.dump(lists, open(os.path.join(out_dir, "lists.json"), "w"))
order = items[:]
rng.shuffle(order)
size = 50
parts = [order[i:i + size] for i in range(0, len(order), size)]
os.makedirs(os.path.join(out_dir, "rater_L"), exist_ok=True)
for i, part in enumerate(parts):
    json.dump([{k: v for k, v in it.items() if k not in ("judge_rating", "bench")} for it in part], open(os.path.join(out_dir, "rater_L", f"part{i + 1}.json"), "w"), indent=0)
print("queries", len(lists), "items", len(items), "parts", len(parts), "judge dist", sorted(__import__("collections").Counter(it["judge_rating"] for it in items).items(), key=str))
