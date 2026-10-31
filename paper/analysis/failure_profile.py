import collections
import glob
import json
import os
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import FAMILIES, ULT, account_side  # noqa: E402

site, pairs_json, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
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
        for e, entry in rep["engines"].items():
            p = os.path.join(d, entry.get("per_query_path", ""))
            if e == ULT or (e in FAMILIES and e != "brave-llmcontext") or not os.path.isfile(p):
                continue
            pq = json.load(open(p))["per_query"]
            n = len(pq)
            for qi, q in enumerate(pq):
                totals[e] += 1
                if q.get("search_error") and account_side(q["search_error"]):
                    by_date[e][name[:10]] += 1
                    by_pos[e]["first half" if qi < n / 2 else "second half"] += 1
                    err = q["search_error"]
                    records.append({"engine": e, "bench": bench, "run": name, "query_index": qi, "error_type": err.get("error_type"), "message": (err.get("error_message") or "")[:80]})
for e in sorted(by_date):
    tot = sum(by_date[e].values())
    days = sorted(by_date[e].items())
    top = sorted(days, key=lambda kv: -kv[1])[:3]
    print(f"{e:16s} account-side failures {tot} of {totals[e]} requests on {len(days)} days; top days {top}; first half {by_pos[e]['first half']} second half {by_pos[e]['second half']}")
json.dump({"by_date": {e: dict(v) for e, v in by_date.items()}, "by_position": {e: dict(v) for e, v in by_pos.items()}, "requests": {e: totals[e] for e in by_date}, "records": records}, open(out_path, "w"), indent=1)
print("records", len(records))
