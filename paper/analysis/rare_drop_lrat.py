import collections
import glob
import json
import os
import re
import sys

from common import KEEP, SITE_RE

from needle.agentic_rare.cli import DEFAULT_FILTERED_PATH
from needle.agentic_rare.io import iter_rows, resolve_dataset
from needle.shared.hf import DEFAULT_DATASET

DROP = "LRAT-Train"
SCAN = {"email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "url": re.compile(r"https?://|www\.", re.I),
        "host": re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,6}\b", re.I),
        "mixed_token": re.compile(r"\b(?=\w*\d)(?=\w*[a-z])(?=\w*[A-Z])\w{20,}\b")}

site, pairs_json, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
table_runs = {ts.replace(":", "") for ts in json.load(open(pairs_json))["runs"]}
rows = list(iter_rows(resolve_dataset(None, DEFAULT_DATASET, DEFAULT_FILTERED_PATH)))
source = {r["query_text"]: r["source"] for r in rows}
filtered_by_source = collections.Counter(r["source"] for r in rows)

tot = collections.defaultdict(lambda: [0.0, 0])
tot_drop = collections.defaultdict(lambda: [0.0, 0])
src_count = collections.Counter()
released = set()
for d in sorted(glob.glob(os.path.join(site, "hfrare", "*"))):
    if os.path.basename(d) not in table_runs or not os.path.exists(os.path.join(d, "agentic_rare.json")):
        continue
    released |= {json.loads(line)["query_text"] for line in open(os.path.join(d, "agentic_rare.jsonl")) if line.strip()}
    rep = json.load(open(os.path.join(d, "agentic_rare.json")))
    per = {}
    for e, v in rep["engines"].items():
        p = os.path.join(d, v.get("per_query_path", ""))
        if e in KEEP and os.path.isfile(p):
            per[e] = {q["query"]: q for q in json.load(open(p))["per_query"]}
    queries = set.union(*[set(v) for v in per.values()])
    for q in sorted(queries):
        s = source.get(q, "unknown")
        src_count[s] += 1
        for e in per:
            r = per[e].get(q)
            if r is None or r.get("ndcg") is None:
                continue
            tot[e][0] += r["ndcg"]
            tot[e][1] += 1
            if s != DROP:
                tot_drop[e][0] += r["ndcg"]
                tot_drop[e][1] += 1
deltas = {e: tot_drop[e][0] / tot_drop[e][1] - tot[e][0] / tot[e][1] for e in sorted(tot)}
n_runs = sum(src_count.values())
scan = {k: sorted(q for q in released if rx.search(q)) for k, rx in SCAN.items()}
out = {
    "filtered_path": DEFAULT_FILTERED_PATH,
    "filtered_queries": len(rows),
    "filtered_by_source": dict(sorted(filtered_by_source.items())),
    "query_runs": n_runs,
    "query_runs_by_source": dict(sorted(src_count.items())),
    "query_run_share_by_source": {s: n / n_runs for s, n in sorted(src_count.items())},
    "released_queries": len(released),
    "scan_counts_released": {k: len(v) for k, v in scan.items()},
    "host_with_site_operator": sum(1 for q in scan["host"] if SITE_RE.search(q)),
    "scan_matches_released": scan,
    "delta_mean_ndcg": deltas,
    "max_abs_delta": max(abs(v) for v in deltas.values()),
}
json.dump(out, open(out_path, "w"), indent=1)
print("filtered:", len(rows), dict(filtered_by_source))
print("query-runs by source:", dict(src_count), "of", n_runs)
print("released queries:", len(released), "scan matches:", out["scan_counts_released"])
print("max |delta mean ndcg| dropping LRAT:", out["max_abs_delta"])
