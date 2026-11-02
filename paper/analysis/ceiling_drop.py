import glob
import json
import os
import sys

from common import KEEP, ULT, order_tau

from needle.shared.rankeval import QueryRun, _fully_judged
from needle.shared.search.errors import account_side

site, pairs_json, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
table_runs = {ts.replace(":", "") for ts in json.load(open(pairs_json))["runs"]}


def shares(sel, zero_variant):
    use = sel if zero_variant else [r for r in sel if r["u"] > 0]
    um = sum(r["u"] for r in use) / len(use)
    return {e: (sum(r["vals"][e] for r in use if e in r["vals"]) / len([r for r in use if e in r["vals"]])) / um for e in KEEP}


def counts(sel):
    judged = [r for r in sel if r["judged"]]
    return {"query_runs": len(sel), "judge_error": len(sel) - len(judged), "fully_judged": len(judged), "empty_ceiling": sum(1 for r in judged if r["u"] <= 0)}


res = {}
for bench, folder, report in (("news", "hfnews", "ndcg.json"), ("agentic_rare", "hfrare", "agentic_rare.json")):
    rows, runs, incomplete = [], [], []
    for d in sorted(glob.glob(os.path.join(site, folder, "*"))):
        name = os.path.basename(d)
        if name not in table_runs:
            continue
        paths = {}
        if os.path.exists(os.path.join(d, report)):
            paths = {e: os.path.join(d, v.get("per_query_path", "")) for e, v in json.load(open(os.path.join(d, report)))["engines"].items()}
        if not paths or not all(os.path.isfile(p) for p in paths.values()):
            incomplete.append(name)
            continue
        runs.append(name)
        pqs = {e: json.load(open(p))["per_query"] for e, p in paths.items()}
        for qi, ult in enumerate(pqs[ULT]):
            judged = _fully_judged(QueryRun(searches=[], judgements=[pq[qi]["ratings"] for e, pq in pqs.items() if e != ULT], n_judged=0, profile=None))
            vals = {}
            for e in KEEP:
                pq = pqs[e][qi]
                if pq.get("search_error") and account_side(pq["search_error"]):
                    continue
                vals[e] = 0.0 if pq.get("search_error") else float(pq.get("ndcg") or 0.0)
            rows.append({"judged": judged, "u": float(ult.get("ndcg") or 0.0), "vals": vals, "quoted": ult["query"].count('"') >= 2})
    info = {"runs": len(runs), "incomplete": incomplete, **counts(rows)}
    info["share"] = info["empty_ceiling"] / info["fully_judged"]
    if bench == "agentic_rare":
        info["quoted"] = counts([r for r in rows if r["quoted"]])
        info["unquoted"] = counts([r for r in rows if not r["quoted"]])
    judged = [r for r in rows if r["judged"]]
    std, zero = shares(judged, False), shares(judged, True)
    o1 = sorted(KEEP, key=lambda e: -std[e])
    o2 = sorted(KEEP, key=lambda e: -zero[e])
    moves = sorted(KEEP, key=lambda e: -abs(zero[e] - std[e]))
    info["zero_variant"] = {"tau_b": order_tau(o1, o2), "moves": [(e, round(zero[e] - std[e], 4)) for e in moves], "order_changes": [(a, b) for a, b in zip(o1, o2, strict=True) if a != b]}
    res[bench] = info
    print(bench, json.dumps(info))
json.dump(res, open(out_path, "w"), indent=1)
