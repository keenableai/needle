import collections
import glob
import json
import os
import sys

site, pairs_json, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
ACCOUNT = ["perplexity", "exa", "kagi", "parallel", "claude-search"]
BENCHES = {"scholar": ("hfscholar", "scholar.json"), "news": ("hfnews", "ndcg.json"), "finance": ("hf", "recall.json"), "agentic_rare": ("hfrare", "agentic_rare.json"), "legal": ("hflegal", "legal.json")}
table_runs = {ts.replace(":", "") for ts in json.load(open(pairs_json))["runs"]}
by_date = collections.defaultdict(collections.Counter)
by_pos = collections.defaultdict(collections.Counter)
totals = collections.Counter()
records = []
for bench, (folder, report) in BENCHES.items():
    for d in sorted(glob.glob(os.path.join(site, folder, "*"))):
        name = os.path.basename(d)
        if name not in table_runs or not os.path.exists(os.path.join(d, report)):
            continue
        rep = json.load(open(os.path.join(d, report)))
        for e in ACCOUNT:
            p = os.path.join(d, rep["engines"].get(e, {}).get("per_query_path", ""))
            if not os.path.isfile(p):
                continue
            pq = json.load(open(p))["per_query"]
            n = len(pq)
            for qi, q in enumerate(pq):
                totals[e] += 1
                if q.get("search_error"):
                    by_date[e][name[:10]] += 1
                    by_pos[e]["first half" if qi < n / 2 else "second half"] += 1
                    err = q["search_error"] if isinstance(q["search_error"], dict) else {"error_message": str(q["search_error"])}
                    records.append({"engine": e, "bench": bench, "run": name, "query_index": qi, "error_type": err.get("error_type"), "message": (err.get("error_message") or "")[:80]})
for e in ACCOUNT:
    tot = sum(by_date[e].values())
    if not tot:
        print(e, "no account-side failures in the window")
        continue
    days = sorted(by_date[e].items())
    top = sorted(days, key=lambda kv: -kv[1])[:3]
    print(f"{e:14s} failures {tot} of {totals[e]} requests on {len(days)} days; top days {top}; first half {by_pos[e]['first half']} second half {by_pos[e]['second half']}")
json.dump({"by_date": {e: dict(v) for e, v in by_date.items()}, "by_position": {e: dict(v) for e, v in by_pos.items()}, "requests": dict(totals), "records": records}, open(out_path, "w"), indent=1)
print("records", len(records))
