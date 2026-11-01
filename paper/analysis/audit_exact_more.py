import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from strict_v2 import gold_queries, gold_rows, prose_hit  # noqa: E402

hf_dir, sample_json, out_json, n_new = Path(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4])
LO, HI = "2026-10-17", "2026-10-30"
ENGINES = [
    "keenable", "exa", "brave-llmcontext", "perplexity", "parallel", "brave", "you", "linkup",
    "deepseek", "context", "kagi", "firecrawl", "chatgpt-search", "google", "octen", "bing",
    "claude-search", "jina", "tavily", "tinyfish", "ceramic",
]
rng = random.Random(23)


old = json.load(open(sample_json))
seen = {(s["run"], s["engine"], s["query"], s["url"]) for s in old}
pool = []
for run in sorted(p for p in hf_dir.iterdir() if p.is_dir() and LO <= p.name[:10] < HI):
    rows = gold_rows(run / "gold.jsonl")
    gold = {g["query_text"]: g["gold"] for g in rows}
    queries = gold_queries(rows)
    for eng in ENGINES:
        p = run / "recall" / f"{eng}.json"
        if not p.exists():
            continue
        for pq in json.load(open(p))["per_query"]:
            if pq["search_error"] is not None:
                continue
            g = gold.get(pq["query"])
            if g is None or g["field_type"] != "money":
                continue
            for rank, r in enumerate(pq["results"][:5]):
                if not r.get("det_match"):
                    continue
                if prose_hit(queries[pq["query"]], r) and (run.name, eng, pq["query"], r["url"]) not in seen:
                    pool.append((run.name, eng, pq["query"], g, rank, r))
print("exact-stratum pool (window runs, not yet audited):", len(pool))
sample = []
for run_id, eng, q, g, rank, r in rng.sample(pool, min(n_new, len(pool))):
    sample.append({
        "id": len(sample), "kind": "money_exact", "run": run_id, "engine": eng, "query": q,
        "field": g["field"], "field_type": g["field_type"], "gold": g["value"], "aliases": g["aliases"],
        "rank": rank + 1, "title": r.get("title"), "url": r["url"], "snippet": (r.get("snippet") or "")[:700],
    })
json.dump(sample, open(out_json, "w"), indent=1)
print("sampled", len(sample))
