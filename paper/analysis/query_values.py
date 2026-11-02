import collections
import json
import os

from common import KEEP
from finance_runs import finance_run

from needle.shared.search.errors import account_side

BENCHES = {"scholar": ("hfscholar", "scholar.json", "recall"), "news": ("hfnews", "ndcg.json", "ndcg"), "finance": ("hf", "recall.json", "recall"),
           "agentic_rare": ("hfrare", "agentic_rare.json", "ndcg"), "legal": ("hflegal", "legal.json", "recall")}


def answered_value(bench, q):
    if bench in ("news", "agentic_rare"):
        return q["ndcg"]
    if bench == "finance":
        return q["score"]
    return float(q["hit_rank"] is not None)


def values(bench, eng, pq, ult_hits, ceiling):
    if eng == "ultimate" and bench in ("finance", "legal"):
        return [float(ult_hits[q["query"]]) for q in pq]
    return [(None if account_side(q["search_error"]) or not c else 0.0) if q["search_error"] is not None else answered_value(bench, q)
            for q, c in zip(pq, ceiling, strict=False)]


def load_run(d, bench):
    rep = json.load(open(os.path.join(d, BENCHES[bench][1])))
    pqs = {e: json.load(open(os.path.join(d, v["per_query_path"])))["per_query"] for e, v in rep["engines"].items()
           if os.path.isfile(os.path.join(d, v.get("per_query_path", "")))}
    if "ultimate" not in pqs or any(e not in pqs for e in KEEP):
        return None
    if bench == "finance":
        pqs = {e: v["per_query"] for e, v in finance_run(d)[0]["engines"].items()}
    return pqs


def run_values(bench, pqs):
    ult_hits = collections.defaultdict(bool)
    ceiling = [q["ndcg"] is not None for q in pqs["ultimate"]] if BENCHES[bench][2] == "ndcg" else [True] * len(pqs["ultimate"])
    engines = [e for e in pqs if e != "ultimate"] + ["ultimate"] if bench in ("finance", "legal") else KEEP + ["ultimate"]
    out = {}
    for e in engines:
        v = values(bench, e, pqs[e], ult_hits, ceiling)
        if bench in ("finance", "legal") and e != "ultimate":
            for q, x in zip(pqs[e], v, strict=False):
                ult_hits[q["query"]] |= bool(x)
        if e in KEEP or e == "ultimate":
            out[e] = v
    return out
