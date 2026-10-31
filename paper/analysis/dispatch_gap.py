import glob
import json
import os
import sys
from datetime import datetime

site = sys.argv[1]
LO, HI = "2026-10-17", "2026-10-30"
KEEP = "keenable exa google bing brave brave-llmcontext parallel perplexity tavily linkup tinyfish octen ceramic you firecrawl kagi jina context deepseek claude-search chatgpt-search".split()


def ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ")


gaps = []
spans = []
order_first = {}
for bench, folder, report in (("news", "hfnews", "ndcg.json"), ("agentic_rare", "hfrare", "agentic_rare.json")):
    for d in sorted(glob.glob(os.path.join(site, folder, "*"))):
        name = os.path.basename(d)
        if not (LO <= name[:10] < HI) or not os.path.exists(os.path.join(d, report)):
            continue
        rep = json.load(open(os.path.join(d, report)))
        pqs = {}
        for e in KEEP:
            if e in rep["engines"]:
                p = os.path.join(d, rep["engines"][e].get("per_query_path", ""))
                if os.path.isfile(p):
                    pqs[e] = json.load(open(p))["per_query"]
        if len(pqs) < 19:
            continue
        n = len(next(iter(pqs.values())))
        run_times = []
        for qi in range(n):
            times = {e: ts(pqs[e][qi]["queried_at"]) for e in pqs if pqs[e][qi].get("queried_at")}
            if len(times) < 10:
                continue
            lo, hi = min(times.values()), max(times.values())
            gaps.append((hi - lo).total_seconds())
            run_times.extend(times.values())
            first = min(times, key=times.get)
            order_first[first] = order_first.get(first, 0) + 1
        if run_times:
            spans.append((max(run_times) - min(run_times)).total_seconds())
gaps.sort()
spans.sort()


def pct(xs, p):
    return xs[min(len(xs) - 1, int(p * len(xs)))]


print("queries", len(gaps), "runs", len(spans))
print("same-query dispatch spread across engines (s): median %.0f, p90 %.0f, max %.0f" % (pct(gaps, .5), pct(gaps, .9), gaps[-1]))
print("whole-run span (s): median %.0f, p90 %.0f" % (pct(spans, .5), pct(spans, .9)))
print("engine dispatched first most often:", sorted(order_first.items(), key=lambda kv: -kv[1])[:5])
