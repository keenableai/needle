import json
import math
import re
import sys
from pathlib import Path

from needle.shared.metrics import GAIN, normalize_url

hf_dir, history, out_history = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
SITE_RE = re.compile(r"\bsite:")


def dcg(r):
    return sum(GAIN.get(x, 0.0) / math.log2(i + 2) for i, x in enumerate(r[:5]))


rows = []
changed = total = site_q = 0
for run in sorted(p for p in hf_dir.iterdir() if p.is_dir() and (p / "agentic_rare.json").exists()):
    rep = json.load(open(run / "agentic_rare.json"))
    ts = run.name[:13] + ":" + run.name[13:15] + "Z"
    nq = rep["num_queries"]
    for eng, e in rep["engines"].items():
        p = run / e.get("per_query_path", "")
        if not p.exists():
            continue
        scores = []
        errs = 0
        for pq in json.load(open(p))["per_query"]:
            if pq["search_error"] is not None:
                errs += 1
                scores.append(0.0)
                continue
            if pq["ndcg"] is None:
                continue
            total += 1
            is_site = bool(SITE_RE.search(pq["query"].lower()))
            site_q += is_site
            if not is_site or pq["ndcg"] == 0:
                scores.append(pq["ndcg"])
                continue
            idcg = pq["dcg"] / pq["ndcg"] if pq["ndcg"] else None
            seen = set()
            pen = []
            for r, rating in zip(pq["results"], pq["ratings"]):
                u = normalize_url(r["url"])
                pen.append(0 if (u in seen or rating is None) else rating)
                seen.add(u)
            new = dcg(pen) / idcg if idcg else pq["ndcg"]
            changed += abs(new - pq["ndcg"]) > 1e-9
            scores.append(new)
        lat = e.get("latency") or {}
        rows.append({"ts": ts, "bench": "agentic_rare", "engine": eng, "ndcg": sum(scores) / len(scores) if scores else None,
                     "num_scored": len(scores), "num_queries": nq, "search_errors": errs, "judge_errors": e.get("judge_errors", 0),
                     "p50_ms": lat.get("p50_ms"), "p95_ms": lat.get("p95_ms")})
print("engine-query pairs", total, "with site:", site_q, "scores changed by the duplicate penalty", changed)
strict_ts = {r["ts"] for r in rows}
out = []
replaced = 0
for line in open(history):
    if not line.strip():
        continue
    r = json.loads(line)
    if r["bench"] == "agentic_rare" and r["ts"] in strict_ts:
        replaced += 1
        continue
    out.append(r)
out.extend(rows)
with open(out_history, "w") as f:
    for r in out:
        f.write(json.dumps(r) + "\n")
print("replaced", replaced, "rare rows with", len(rows), "over", len(strict_ts), "runs")
