import glob
import json
import os
import sys

from needle.shared.search.errors import account_side

site, pairs_json, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
KEEP = "keenable exa google bing brave brave-llmcontext parallel perplexity tavily linkup tinyfish octen ceramic you firecrawl kagi jina context deepseek claude-search chatgpt-search".split()
table_runs = {ts.replace(":", "") for ts in json.load(open(pairs_json))["runs"]}
res = {}
for bench, folder, report in (("news", "hfnews", "ndcg.json"), ("agentic_rare", "hfrare", "agentic_rare.json")):
    rows = []
    for d in sorted(glob.glob(os.path.join(site, folder, "*"))):
        name = os.path.basename(d)
        if name not in table_runs or not os.path.exists(os.path.join(d, report)):
            continue
        rep = json.load(open(os.path.join(d, report)))
        pqs = {}
        for e in KEEP + ["ultimate"]:
            p = os.path.join(d, rep["engines"].get(e, {}).get("per_query_path", ""))
            if os.path.isfile(p):
                pqs[e] = json.load(open(p))["per_query"]
        if len(pqs) < 22:
            continue
        for qi in range(len(pqs["ultimate"])):
            q = pqs["ultimate"][qi]["query"]
            vals = {}
            for e in KEEP:
                pq = pqs[e][qi]
                if pq.get("search_error") and account_side(pq["search_error"]):
                    continue
                vals[e] = 0.0 if pq.get("search_error") else float(pq.get("ndcg") or 0.0)
            rows.append({"u": float(pqs["ultimate"][qi].get("ndcg") or 0.0), "vals": vals, "quoted": q.count('"') >= 2})
    n = len(rows)
    empty = sum(1 for r in rows if r["u"] <= 0)
    info = {"queries": n, "empty_ceiling": empty, "share": empty / n}
    if bench == "agentic_rare":
        for name, sel in (("quoted", [r for r in rows if r["quoted"]]), ("unquoted", [r for r in rows if not r["quoted"]])):
            info[name] = {"queries": len(sel), "empty_ceiling": sum(1 for r in sel if r["u"] <= 0)}

    def shares(sel, zero_variant):
        use = sel if zero_variant else [r for r in sel if r["u"] > 0]
        um = sum(r["u"] for r in use) / len(use)
        return {e: (sum(r["vals"][e] for r in use if e in r["vals"]) / len([r for r in use if e in r["vals"]])) / um for e in KEEP}

    std, zero = shares(rows, False), shares(rows, True)
    o1 = sorted(KEEP, key=lambda e: -std[e])
    o2 = sorted(KEEP, key=lambda e: -zero[e])

    def tau_b(a, b):
        c = d = 0
        for i in range(len(a)):
            for j in range(i + 1, len(a)):
                x = (a.index(a[i]) - a.index(a[j])) * (b.index(a[i]) - b.index(a[j]))
                c += x > 0
                d += x < 0
        return (c - d) / (c + d)

    moves = sorted(KEEP, key=lambda e: -abs(zero[e] - std[e]))[:3]
    info["zero_variant"] = {"tau_b": tau_b(o1, o2), "max_moves": [(e, round(zero[e] - std[e], 3)) for e in moves], "order_changes": [(a, b) for a, b in zip(o1, o2) if a != b]}
    res[bench] = info
    print(bench, json.dumps(info))
json.dump(res, open(out_path, "w"), indent=1)
