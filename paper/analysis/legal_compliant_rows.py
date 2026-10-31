import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

hf_dir, history, out_history = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
SITE_RE = re.compile(r"site:(\S+)")


def host_ok(url, site):
    h = (urlsplit(url).hostname or "").lower()
    return h == site or h.endswith("." + site)


rows = []
changed = 0
for run in sorted(p for p in hf_dir.iterdir() if p.is_dir() and (p / "legal.json").exists()):
    rep = json.load(open(run / "legal.json"))
    ts = run.name[:13] + ":" + run.name[13:15] + "Z"
    nq = rep["num_queries"]
    any_hit = defaultdict(bool)
    for eng, e in rep["engines"].items():
        p = run / e.get("per_query_path", "")
        if eng == "ultimate" or not p.exists():
            continue
        hits = errs = n = 0
        for pq in json.load(open(p))["per_query"]:
            n += 1
            if pq.get("search_error") is not None:
                errs += 1
                continue
            hit = pq.get("hit_rank") is not None
            m = SITE_RE.search(pq["query"])
            if hit and m:
                site = m.group(1).lower().strip('"')
                r = pq["results"][pq["hit_rank"] - 1]
                if not host_ok(r["url"], site):
                    hit = False
                    changed += 1
            hits += hit
            any_hit[pq["query"]] |= hit
        lat = e.get("latency") or {}
        rows.append({"ts": ts, "bench": "legal", "engine": eng, "recall": hits / n if n else None, "num_scored": n,
                     "num_queries": n, "search_errors": errs, "p50_ms": lat.get("p50_ms"), "p95_ms": lat.get("p95_ms")})
    rows.append({"ts": ts, "bench": "legal", "engine": "ultimate", "recall": sum(any_hit.values()) / nq, "num_scored": nq,
                 "num_queries": nq, "search_errors": 0, "p50_ms": None, "p95_ms": None})
print("legal site: hits revoked for host mismatch", changed)
ts_set = {r["ts"] for r in rows}
out = []
replaced = 0
for line in open(history):
    if not line.strip():
        continue
    r = json.loads(line)
    if r["bench"] == "legal" and r["ts"] in ts_set:
        replaced += 1
        continue
    out.append(r)
out.extend(rows)
with open(out_history, "w") as f:
    for r in out:
        f.write(json.dumps(r) + "\n")
print("replaced", replaced, "legal rows with", len(rows), "over", len(ts_set), "runs")
