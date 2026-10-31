import collections
import glob
import json
import os
import sys

site, pairs_json, out_path = sys.argv[1:4]
table_runs = {ts.replace(":", "") for ts in json.load(open(pairs_json))["runs"]}
BENCHES = {"scholar": ("hfscholar", "scholar.json"), "news": ("hfnews", "ndcg.json"), "finance": ("hf", "recall.json"), "agentic_rare": ("hfrare", "agentic_rare.json"), "legal": ("hflegal", "legal.json")}
res = {}
for bench, (folder, report) in BENCHES.items():
    runs_of = collections.defaultdict(set)
    nq = 0
    for d in sorted(glob.glob(os.path.join(site, folder, "*"))):
        name = os.path.basename(d)
        if name not in table_runs or not os.path.exists(os.path.join(d, report)):
            continue
        rep = json.load(open(os.path.join(d, report)))
        e = next((v for k, v in rep["engines"].items() if k != "ultimate" and "per_query_path" in v), None)
        if e is None:
            continue
        p = os.path.join(d, e["per_query_path"])
        if not os.path.isfile(p):
            continue
        for q in json.load(open(p))["per_query"]:
            runs_of[q["query"]].add(name)
            nq += 1
    repeated_texts = sum(1 for v in runs_of.values() if len(v) > 1)
    repeated_runs = sum(len(v) for v in runs_of.values() if len(v) > 1)
    days = {q: {r[:10] for r in v} for q, v in runs_of.items()}
    cross_day = sum(len(v) for q, v in runs_of.items() if len(days[q]) > 1)
    res[bench] = {"query_runs": nq, "distinct_texts": len(runs_of), "texts_in_more_than_one_run": repeated_texts, "query_runs_of_repeated_texts": repeated_runs, "query_runs_of_texts_on_more_than_one_day": cross_day}
    print(f"{bench:13s} query-runs {nq:6d} distinct {len(runs_of):6d} repeated texts {repeated_texts:5d} ({repeated_runs / nq if nq else 0:.1%} of query-runs) cross-day {cross_day / nq if nq else 0:.1%}")
json.dump(res, open(out_path, "w"), indent=1)
