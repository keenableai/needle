import json
import random
import sys
from pathlib import Path

from needle.finance.canon import cached_squad_norm, parse_amount, phrase_in, squad_norm, text_amounts
from needle.finance.models import cues_for

hf_dir, sample_json, out_json, n_new = Path(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4])
LO, HI = "2026-10-17", "2026-10-30"
ENGINES = [
    "keenable", "exa", "brave-llmcontext", "perplexity", "parallel", "brave", "you", "linkup",
    "deepseek", "context", "kagi", "firecrawl", "chatgpt-search", "google", "octen", "bing",
    "claude-search", "jina", "tavily", "tinyfish", "ceramic",
]
rng = random.Random(23)


def text_of(r):
    return " ".join(p for p in (r.get("title"), (r.get("snippet") or "")[:2000]) if p)


def amount_match(value, aliases, text, tol, cues):
    norm = squad_norm(text)
    if cues and not any(phrase_in(cached_squad_norm(c), norm) for c in cues):
        return False
    amounts = text_amounts(text, skip_year_like=True)
    for form in [f for f in [value, *aliases] if f not in (None, "")]:
        gold = parse_amount(form)
        if gold is None:
            continue
        for amount in amounts:
            if gold == 0:
                if abs(amount) < 1:
                    return True
            elif abs(amount - gold) / abs(gold) <= tol:
                return True
    return False


old = json.load(open(sample_json))
seen = {(s["run"], s["engine"], s["query"], s["url"]) for s in old}
pool = []
for run in sorted(p for p in hf_dir.iterdir() if p.is_dir() and LO <= p.name[:10] < HI):
    gold = {}
    for line in open(run / "gold.jsonl"):
        if line.strip():
            g = json.loads(line)
            gold[g["query_text"]] = g["gold"]
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
            aliases = tuple(str(a) for a in g["aliases"] or [])
            cues = cues_for(g["field"])
            for rank, r in enumerate(pq["results"][:5]):
                if not r.get("det_match"):
                    continue
                if amount_match(g["value"], aliases, text_of(r), 0.001, cues) and (run.name, eng, pq["query"], r["url"]) not in seen:
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
