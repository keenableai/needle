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

hits = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
meta_counts = collections.Counter()
for d in sorted(glob.glob(os.path.join(site, "hfscholar", "*"))):
    name = os.path.basename(d)
    if name not in table_runs or not os.path.exists(os.path.join(d, "scholar.json")):
        continue
    meta = {}
    for line in open(os.path.join(d, "scholar.jsonl")):
        if not line.strip():
            continue
        g = json.loads(line)
        gold = json.loads(g["gold"]) if isinstance(g["gold"], str) else g["gold"]
        origin = json.loads(g["query_origin"]) if isinstance(g["query_origin"], str) else g["query_origin"]
        meta[g["query_text"]] = (gold.get("domain", "?"), gold.get("age_bucket", "?"), origin.get("bucket", "?"))
    rep = json.load(open(os.path.join(d, "scholar.json")))
    for e in KEEP:
        p = os.path.join(d, rep["engines"].get(e, {}).get("per_query_path", ""))
        if not os.path.isfile(p):
            continue
        for q in json.load(open(p))["per_query"]:
            if q.get("search_error") and account_side(q["search_error"]):
                continue
            m = meta.get(q["query"]) or meta.get(q["query"][:60])
            if m is None:
                meta_counts["unmatched"] += 1
                continue
            dom, age, bucket = m
            for key in ((f"domain:{dom}"), (f"age:{age}"), (f"bucket:{bucket}"), "all"):
                hits[e][key][1] += 1
                hits[e][key][0] += q.get("hit_rank") is not None
print("unmatched", meta_counts["unmatched"])
strata = sorted({k for e in hits for k in hits[e]})
res = {}
print(f"{'stratum':28s} {'n':>5s} {'keenable':>9s} {'exa':>7s} {'gap':>6s} {'leader':>14s}")
for k in strata:
    n = hits["keenable"][k][1]
    rec = {e: hits[e][k][0] / hits[e][k][1] for e in KEEP if hits[e][k][1]}
    leader = max(rec, key=rec.get)
    res[k] = {"n": n, "recall": rec, "leader": leader}
    print(f"{k:28s} {n:5d} {rec['keenable']:9.3f} {rec['exa']:7.3f} {rec['keenable']-rec['exa']:+6.3f} {leader:>14s}")
json.dump(res, open(out_path, "w"), indent=1)
