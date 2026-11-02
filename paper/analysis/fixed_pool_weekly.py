import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from common import tau_b

from needle.shared.metrics import dcg_at_k, normalize_url

hf_dir = Path(sys.argv[1])
CORE = ["bing", "brave", "brave-llmcontext", "ceramic", "exa", "firecrawl", "google", "kagi", "keenable", "octen", "parallel", "perplexity", "tavily", "tinyfish", "you"]

full = defaultdict(lambda: defaultdict(list))
core = defaultdict(lambda: defaultdict(list))
for run in sorted(p for p in hf_dir.iterdir() if p.is_dir() and (p / "ndcg.json").exists()):
    week = datetime.strptime(run.name[:10], "%Y-%m-%d").strftime("%G-W%V")
    rep = json.load(open(run / "ndcg.json"))
    eng = {}
    for name, e in rep["engines"].items():
        p = run / e.get("per_query_path", "")
        if name == "ultimate" or not p.exists():
            continue
        for pq in json.load(open(p))["per_query"]:
            if pq["search_error"] is not None or pq.get("judge_errors") or pq["ndcg"] is None:
                continue
            eng.setdefault(pq["query"], {})[name] = pq
    for d in eng.values():
        pool_all, pool_core = {}, {}
        for name, pq in d.items():
            for r in pq["results"]:
                if r.get("rating") is None:
                    continue
                u = normalize_url(r["url"])
                pool_all[u] = max(pool_all.get(u, 0), r["rating"])
                if name in CORE:
                    pool_core[u] = max(pool_core.get(u, 0), r["rating"])
        ia = dcg_at_k(sorted(pool_all.values(), reverse=True))
        ic = dcg_at_k(sorted(pool_core.values(), reverse=True))
        for name, pq in d.items():
            if name not in CORE:
                continue
            d_ = dcg_at_k(pq["penalized_ratings"])
            if ia > 0:
                full[week][name].append(d_ / ia)
            if ic > 0:
                core[week][name].append(min(1.0, d_ / ic))

weeks = sorted(full)
print("weeks", weeks)
for w in weeks:
    f = {e: sum(v) / len(v) for e, v in full[w].items()}
    c = {e: sum(v) / len(v) for e, v in core[w].items()}
    names = sorted(set(f) & set(c))
    print(w, f"tau_b full-pool vs core-pool shares {tau_b([f[e] for e in names], [c[e] for e in names]):.3f}",
          f"mean core-full diff {sum(c[e] - f[e] for e in names) / len(names):+.3f}",
          f"keenable {f.get('keenable', 0):.3f}/{c.get('keenable', 0):.3f} perplexity {f.get('perplexity', 0):.3f}/{c.get('perplexity', 0):.3f}")
