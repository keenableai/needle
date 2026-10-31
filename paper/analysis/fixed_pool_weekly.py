import json
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from needle.shared.metrics import GAIN, normalize_url

hf_dir = Path(sys.argv[1])
CORE = ["bing", "brave", "brave-llmcontext", "ceramic", "exa", "firecrawl", "google", "kagi", "keenable", "octen", "parallel", "perplexity", "tavily", "tinyfish", "you"]


def dcg(r):
    return sum(GAIN.get(x, 0.0) / math.log2(i + 2) for i, x in enumerate(r[:5]))


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
    for q, d in eng.items():
        pool_all, pool_core = {}, {}
        for name, pq in d.items():
            for r in pq["results"]:
                if r.get("rating") is None:
                    continue
                u = normalize_url(r["url"])
                pool_all[u] = max(pool_all.get(u, 0), r["rating"])
                if name in CORE:
                    pool_core[u] = max(pool_core.get(u, 0), r["rating"])
        ia = dcg(sorted(pool_all.values(), reverse=True))
        ic = dcg(sorted(pool_core.values(), reverse=True))
        for name, pq in d.items():
            if name not in CORE:
                continue
            d_ = dcg(pq["penalized_ratings"])
            if ia > 0:
                full[week][name].append(d_ / ia)
            if ic > 0:
                core[week][name].append(min(1.0, d_ / ic))


def tau_b(a, b):
    n = len(a); c = d = ta = tb = 0
    for i in range(n):
        for j in range(i + 1, n):
            x, y = a[i] - a[j], b[i] - b[j]
            if x == 0 and y == 0:
                continue
            if x == 0:
                ta += 1
            elif y == 0:
                tb += 1
            elif x * y > 0:
                c += 1
            else:
                d += 1
    return (c - d) / (((c + d + ta) * (c + d + tb)) ** 0.5)


weeks = sorted(full)
print("weeks", weeks)
for w in weeks:
    f = {e: sum(v) / len(v) for e, v in full[w].items()}
    c = {e: sum(v) / len(v) for e, v in core[w].items()}
    names = sorted(set(f) & set(c))
    print(w, "tau_b full-pool vs core-pool shares %.3f" % tau_b([f[e] for e in names], [c[e] for e in names]),
          "mean core-full diff %+.3f" % (sum(c[e] - f[e] for e in names) / len(names)),
          "keenable %.3f/%.3f perplexity %.3f/%.3f" % (f.get("keenable", 0), c.get("keenable", 0), f.get("perplexity", 0), c.get("perplexity", 0)))
