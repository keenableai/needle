import json
import os
import statistics
import sys

from scipy.stats import spearmanr

from needle.shared.search import DEFAULT_SNIPPET_CHARS, SearchResult, capped_snippet

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import NAMES, load, shares

hist, site, out_json = sys.argv[1], sys.argv[2], sys.argv[3]
spec = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "manifest.json")))["results"]["table_results"]
engines, runs = spec["engines"], set(spec["runs"])
rows = [r for r in load(hist) if r["ts"] in runs]
sh, _ = shares(rows, engines)
ndcg = {e: sh[e]["news"][0] for e in engines}
rank = {e: i + 1 for i, e in enumerate(sorted(engines, key=lambda e: -ndcg[e]))}

lengths = {e: [] for e in engines}
engine_runs = {e: 0 for e in engines}
used, skipped = [], []
for ts in sorted({r["ts"] for r in rows if r["bench"] == "news"}):
    d = os.path.join(site, "hfnews", ts.replace(":", ""))
    if not os.path.isfile(os.path.join(d, "ndcg.json")):
        skipped.append(ts)
        continue
    used.append(ts)
    rep = json.load(open(os.path.join(d, "ndcg.json")))
    for e in engines:
        p = os.path.join(d, rep["engines"].get(e, {}).get("per_query_path", ""))
        if not os.path.isfile(p):
            continue
        engine_runs[e] += 1
        for pq in json.load(open(p))["per_query"]:
            lengths[e] += [len(capped_snippet(SearchResult(url=r["url"], snippet=r.get("snippet")), DEFAULT_SNIPPET_CHARS)) for r in pq.get("results") or []]

med = {e: statistics.median(lengths[e]) for e in engines}
by_len = sorted(engines, key=lambda e: med[e])
rho, p = spearmanr([med[e] for e in engines], [ndcg[e] for e in engines])
summary = {
    "median_range": [med[by_len[0]], med[by_len[-1]]],
    "shortest": by_len[0],
    "longest": by_len[-1],
    "below_200": {e: rank[e] for e in by_len if med[e] < 200},
    "longest_two": {e: rank[e] for e in by_len[-2:]},
    "spearman_median_length_vs_news_ndcg5": rho,
    "spearman_p": p,
}
out = {
    "source": "hfnews per-query artifacts, news runs of manifest table_results; snippet[:2000] as in needle.shared.search.capped_snippet, missing snippet counted as 0",
    "runs_used": used,
    "runs_without_artifact": skipped,
    "engines": {e: {"name": NAMES[e], "median_chars": med[e], "n_results": len(lengths[e]), "n_empty": lengths[e].count(0),
                    "runs": engine_runs[e], "news_ndcg5": ndcg[e], "news_rank": rank[e]} for e in by_len},
    "summary": summary,
}
json.dump(out, open(out_json, "w"), indent=1)
print(f"news runs used {len(used)}, without artifact {skipped}")
for e in by_len:
    print(f"{NAMES[e]:18s} median {med[e]:7.1f}  n {len(lengths[e]):6d}  news {ndcg[e]:.3f}  rank {rank[e]:2d}")
print(json.dumps(summary, indent=1))
