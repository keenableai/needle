import json
import os
import sys
from collections import Counter, defaultdict
from multiprocessing import get_context
from pathlib import Path

src, site, history, out_history = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, src)
import strict_v2  # noqa: E402


def ts_of(run):
    return run.name[:13] + ":" + run.name[13:15] + "Z"


def finance_rows(run):
    return strict_v2.process(run)[0]


def legal_rows(run):
    rep = json.load(open(run / "legal.json"))
    ts, nq = ts_of(run), rep["num_queries"]
    any_hit = defaultdict(bool)
    rows = []
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
            hits += hit
            any_hit[pq["query"]] |= hit
        lat = e.get("latency") or {}
        rows.append({"ts": ts, "bench": "legal", "engine": eng, "recall": hits / n if n else None, "num_scored": n,
                     "num_queries": n, "search_errors": errs, "p50_ms": lat.get("p50_ms"), "p95_ms": lat.get("p95_ms")})
    rows.append({"ts": ts, "bench": "legal", "engine": "ultimate", "recall": sum(any_hit.values()) / nq, "num_scored": nq,
                 "num_queries": nq, "search_errors": 0, "p50_ms": None, "p95_ms": None})
    return rows


def rare_rows(run):
    rep = json.load(open(run / "agentic_rare.json"))
    ts, nq = ts_of(run), rep["num_queries"]
    rows = []
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
            elif pq["ndcg"] is not None:
                scores.append(pq["ndcg"])
        lat = e.get("latency") or {}
        rows.append({"ts": ts, "bench": "agentic_rare", "engine": eng, "ndcg": sum(scores) / len(scores) if scores else None,
                     "num_scored": len(scores), "num_queries": nq, "search_errors": errs, "judge_errors": e.get("judge_errors", 0),
                     "p50_ms": lat.get("p50_ms"), "p95_ms": lat.get("p95_ms")})
    return rows


def runs_of(folder, report):
    return sorted(p for p in (site / folder).iterdir() if (p / report).exists())


lines = open(history).readlines()
legal_rescored_ts = {r["ts"] for r in map(json.loads, lines) if r["bench"] == "legal" and "mrr" not in r}
with get_context("fork").Pool(8) as pool:
    parts = pool.map(finance_rows, runs_of("hf", "recall.json"))
parts += [legal_rows(r) for r in runs_of("hflegal", "legal.json") if ts_of(r) in legal_rescored_ts]
parts += [rare_rows(r) for r in runs_of("hfrare", "agentic_rare.json")]
new = {(r["ts"], r["bench"], r["engine"]): r for part in parts for r in part}
rescored = len(new)
changed = Counter()
with open(out_history, "w") as f:
    for line in lines:
        r = json.loads(line)
        k = (r["ts"], r["bench"], r["engine"])
        if k in new:
            out = json.dumps(new.pop(k)) + "\n"
            changed[r["bench"]] += out != line
            line = out
        f.write(line)
assert not new, sorted(new)[:5]
print("rescored rows", rescored, "changed by bench", dict(changed))
