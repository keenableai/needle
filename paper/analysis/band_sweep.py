import functools
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import patch

src, hf_dir, out_json, sample_json = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
sys.path.insert(0, src)
from needle.finance import canon
from needle.finance.models import cues_for
from needle.shared.search import SearchResult, titled_snippet

ENGINES = [
    "keenable", "exa", "brave-llmcontext", "perplexity", "parallel", "brave", "you", "linkup",
    "deepseek", "context", "kagi", "firecrawl", "chatgpt-search", "google", "octen", "bing",
    "claude-search", "jina", "tavily", "tinyfish", "ceramic",
]
MONEY_TOLS = [0.0, 0.001, 0.005, 0.01, 0.02, 0.05, 0.10]
HEAD_TOLS = [0.0, 0.01, 0.05, 0.15, 0.25, 0.50]
K = 5
canon.text_amounts = functools.lru_cache(maxsize=None)(canon.text_amounts)


def text_of(r):
    return titled_snippet(SearchResult(url=r["url"], title=r.get("title"), snippet=r.get("snippet")), 0)


def amount_match(ft, value, aliases, text, tol, cues):
    with patch.multiple(canon, MONEY_REL_TOL=tol, HEADCOUNT_REL_TOL=tol, _match_table_figure=lambda *a, **k: False):
        return canon.gold_in_text(ft, value, aliases, text=text, cues=cues)


gold = {}
runs = sorted(p for p in hf_dir.iterdir() if p.is_dir())
for run in runs:
    for line in open(run / "gold.jsonl"):
        if line.strip():
            g = json.loads(line)
            gold[g["query_text"]] = g["gold"]

stats = {
    "runs": len(runs), "judged_runs": 0, "engine_queries": 0, "det_hits": 0,
    "det_miss_judged": 0, "judge_upgrades": 0, "judge_errors_queries": 0,
    "by_type_queries": Counter(), "by_type_det_hits": Counter(), "by_type_upgrades": Counter(),
    "by_type_miss_judged": Counter(),
}
sweep = {"money": {t: defaultdict(lambda: [0, 0]) for t in MONEY_TOLS},
         "numeric_band": {t: defaultdict(lambda: [0, 0]) for t in HEAD_TOLS}}
other_hits = defaultdict(lambda: [0, 0])
kinds = Counter()
pool = defaultdict(list)
rng = random.Random(7)

for run in runs:
    rep = json.load(open(run / "recall.json"))
    judged_run = bool(rep.get("judged"))
    stats["judged_runs"] += judged_run
    for eng in ENGINES:
        p = run / "recall" / f"{eng}.json"
        if not p.exists():
            continue
        for pq in json.load(open(p))["per_query"]:
            if pq["search_error"] is not None:
                continue
            g = gold.get(pq["query"])
            if g is None:
                continue
            ft, aliases, cues = g["field_type"], tuple(str(a) for a in g["aliases"] or []), cues_for(g["field"])
            stats["engine_queries"] += 1
            stats["by_type_queries"][ft] += 1
            det_hit = pq["det_rank"] is not None
            stats["det_hits"] += det_hit
            stats["by_type_det_hits"][ft] += det_hit
            if not det_hit and pq["judged"] and not pq["judge_errors"]:
                stats["det_miss_judged"] += 1
                stats["by_type_miss_judged"][ft] += 1
                if pq["hit_rank"] is not None:
                    stats["judge_upgrades"] += 1
                    stats["by_type_upgrades"][ft] += 1
            if pq["judge_errors"]:
                stats["judge_errors_queries"] += 1
            results = pq["results"][:K]
            if ft in sweep:
                tols = MONEY_TOLS if ft == "money" else HEAD_TOLS
                default = 0.02 if ft == "money" else 0.15
                tight = 0.001 if ft == "money" else 0.01
                for t in tols:
                    hit = any(amount_match(ft, g["value"], aliases, text_of(r), t, cues) for r in results)
                    sweep[ft][t][eng][0] += hit
                    sweep[ft][t][eng][1] += 1
                for rank, r in enumerate(results):
                    if not r["det_match"]:
                        continue
                    tight_hit = amount_match(ft, g["value"], aliases, text_of(r), tight, cues)
                    kind = f"{ft}_exact" if tight_hit else f"{ft}_banded"
                    kinds[kind] += 1
                    pool[kind].append((run.name, eng, pq["query"], g, rank, r))
            else:
                other_hits[eng][0] += pq["det_rank"] is not None
                other_hits[eng][1] += 1
                for rank, r in enumerate(results):
                    if r["det_match"]:
                        kinds[f"other_{ft}"] += 1
                        pool[f"other_{ft}"].append((run.name, eng, pq["query"], g, rank, r))


def recall(d):
    pairs = [(h, n) for h, n in d.values() if n]
    return sum(h for h, _ in pairs) / sum(n for _, n in pairs)


def kendall(a, b):
    s = 0
    n = len(a)
    for i in range(n):
        for j in range(i + 1, n):
            s += 1 if (a[i] - a[j]) * (b[i] - b[j]) > 0 else -1 if (a[i] - a[j]) * (b[i] - b[j]) < 0 else 0
    return s / (n * (n - 1) / 2)


out = {"stats": {k: (dict(v) if isinstance(v, Counter) else v) for k, v in stats.items()}, "sweep": {}}
for ft, tols in sweep.items():
    default = 0.02 if ft == "money" else 0.15
    base_rank = [tols[default][e][0] / tols[default][e][1] for e in ENGINES if tols[default][e][1]]
    engs = [e for e in ENGINES if tols[default][e][1]]
    out["sweep"][ft] = {}
    for t, d in tols.items():
        vals = [d[e][0] / d[e][1] for e in engs]
        out["sweep"][ft][str(t)] = {"recall": recall(d), "tau_vs_default": kendall(vals, base_rank),
                                    "per_engine": dict(zip(engs, vals))}
out["kinds"] = dict(kinds)
out["other_recall"] = recall(other_hits)
json.dump(out, open(out_json, "w"), indent=1)

print(json.dumps(out["stats"], indent=1))
for ft in sweep:
    print(ft)
    for t, v in out["sweep"][ft].items():
        print(f"  tol {t:>5}: recall {v['recall']:.3f}  tau vs default {v['tau_vs_default']:.3f}")
print("hit kinds", dict(kinds))

plan = {"money_banded": 80, "money_exact": 40, "numeric_band_banded": 40, "numeric_band_exact": 10}
other_total = 60
other_kinds = [k for k in pool if k.startswith("other_")]
other_n = sum(kinds[k] for k in other_kinds)
for k in other_kinds:
    plan[k] = max(1, round(other_total * kinds[k] / other_n))
sample = []
for kind, n in plan.items():
    items = pool.get(kind, [])
    for run_id, eng, q, g, rank, r in rng.sample(items, min(n, len(items))):
        sample.append({
            "id": len(sample), "kind": kind, "run": run_id, "engine": eng, "query": q,
            "field": g["field"], "field_type": g["field_type"], "gold": g["value"], "aliases": g["aliases"],
            "rank": rank + 1, "title": r.get("title"), "url": r["url"], "snippet": (r.get("snippet") or "")[:700],
        })
json.dump(sample, open(sample_json, "w"), indent=1)
print("sample", len(sample), Counter(s["kind"] for s in sample))
