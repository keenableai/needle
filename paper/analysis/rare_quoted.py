import collections
import glob
import json
import os
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import account_side  # noqa: E402

site, pairs_json, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
KEEP = "keenable exa google bing brave brave-llmcontext parallel perplexity tavily linkup tinyfish octen ceramic you firecrawl kagi jina context deepseek claude-search chatgpt-search".split()
table_runs = {ts.replace(":", "") for ts in json.load(open(pairs_json))["runs"]}

rows = []
for d in sorted(glob.glob(os.path.join(site, "hfrare", "*"))):
    name = os.path.basename(d)
    if name not in table_runs or not os.path.exists(os.path.join(d, "agentic_rare.json")):
        continue
    rep = json.load(open(os.path.join(d, "agentic_rare.json")))
    pqs = {}
    for e in KEEP + ["ultimate"]:
        p = os.path.join(d, rep["engines"].get(e, {}).get("per_query_path", ""))
        if os.path.isfile(p):
            pqs[e] = json.load(open(p))["per_query"]
    if len(pqs) < 22:
        continue
    for qi in range(len(pqs["ultimate"])):
        q = pqs["ultimate"][qi]["query"]
        u = float(pqs["ultimate"][qi].get("ndcg") or 0.0)
        vals = {}
        for e in KEEP:
            pq = pqs[e][qi]
            if pq.get("search_error") and account_side(pq["search_error"]):
                continue
            vals[e] = 0.0 if pq.get("search_error") else float(pq.get("ndcg") or 0.0)
        rows.append({"q": q, "u": u, "vals": vals, "quoted": q.count('"') >= 2, "wrapped": q.strip().lower().startswith("query:")})

print("rare queries", len(rows), "quoted", sum(r["quoted"] for r in rows), "wrapped", sum(r["wrapped"] for r in rows), "ceiling>0", sum(1 for r in rows if r["u"] > 0))


def shares(sel):
    use = [r for r in sel if r["u"] > 0]
    um = sum(r["u"] for r in use) / len(use)
    out = {}
    for e in KEEP:
        vs = [r["vals"][e] for r in use if e in r["vals"]]
        out[e] = sum(vs) / len(vs) / um if vs else None
    return out, len(use)


def tau_b(a, b):
    c = d = 0
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            x = (a.index(a[i]) - a.index(a[j])) * (b.index(a[i]) - b.index(a[j]))
            c += x > 0
            d += x < 0
    return (c - d) / (c + d)


full, n_full = shares(rows)
order = sorted(KEEP, key=lambda e: -(full[e] or 0))
res = {"n_full": n_full, "full": full}
for name, sel in (("unquoted", [r for r in rows if not r["quoted"]]), ("quoted", [r for r in rows if r["quoted"]]), ("no_wrapped", [r for r in rows if not r["wrapped"]])):
    sh, n = shares(sel)
    o = sorted(KEEP, key=lambda e: -(sh[e] or 0))
    gaps = {e: (sh[e] or 0) - (full[e] or 0) for e in KEEP}
    big = sorted(KEEP, key=lambda e: -abs(gaps[e]))[:4]
    print(f"{name}: queries {n} tau_b vs all {tau_b(order, o):.3f} top5 {o[:5]} bottom3 {o[-3:]} largest moves {[(e, round(gaps[e], 3)) for e in big]}")
    res[name] = {"n": n, "shares": sh, "tau_b_vs_full": tau_b(order, o), "order": o}
print("full top5", order[:5], "bottom3", order[-3:])
json.dump(res, open(out_path, "w"), indent=1)
