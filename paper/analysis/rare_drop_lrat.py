import collections
import glob
import json
import os
import sys

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

site, pairs_json, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
runs = json.load(open(pairs_json))["runs"]
table_runs = {ts.replace(":", "") for v in (runs.values() if isinstance(runs, dict) else [runs]) for ts in v}
t = pq.read_table(hf_hub_download("keenable-ai/needle-results", "agentic/rare_entity.parquet", repo_type="dataset"))
source = dict(zip(t.column("query_text").to_pylist(), t.column("source").to_pylist()))
GAIN = {4: 1.0, 3: 0.667, 2: 0.117}
import math


def dcg(rs):
    return sum(GAIN.get(r, 0.0) / math.log2(i + 2) for i, r in enumerate(rs[:5]))


tot = collections.defaultdict(lambda: [0.0, 0])
tot_drop = collections.defaultdict(lambda: [0.0, 0])
src_count = collections.Counter()
for d in sorted(glob.glob(os.path.join(site, "hfrare", "*"))):
    if os.path.basename(d) not in table_runs or not os.path.exists(os.path.join(d, "agentic_rare.json")):
        continue
    rep = json.load(open(os.path.join(d, "agentic_rare.json")))
    per = {}
    for e, v in rep["engines"].items():
        p = os.path.join(d, v.get("per_query_path", ""))
        if e == "ultimate" or not os.path.isfile(p):
            continue
        per[e] = {q["query"]: q for q in json.load(open(p))["per_query"]}
    queries = set.union(*[set(v) for v in per.values()])
    for q in queries:
        s = source.get(q, "unknown")
        src_count[s] += 1
        for e in per:
            r = per[e].get(q)
            if r is None or r.get("search_error") is not None or r.get("ndcg") is None:
                continue
            tot[e][0] += r["ndcg"]
            tot[e][1] += 1
            if s != "LRAT-Train":
                tot_drop[e][0] += r["ndcg"]
                tot_drop[e][1] += 1
print("query-runs by source:", dict(src_count))
deltas = {}
for e in sorted(tot):
    a = tot[e][0] / tot[e][1]
    b = tot_drop[e][0] / tot_drop[e][1]
    deltas[e] = b - a
print("max |delta mean ndcg| dropping LRAT:", max(abs(v) for v in deltas.values()))
json.dump({"query_runs_by_source": dict(src_count), "delta_mean_ndcg": deltas}, open(out_path, "w"), indent=1)
