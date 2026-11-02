import collections
import json
import random
import sys

from common import ULT, load, tau_b, wmean
from finance_runs import gold_queries, gold_rows, prose_hit

from needle.shared.cli import as_obj

queries_path, report_path, hist_path, pairs_json, out_dir = sys.argv[1:6]
rng = random.Random(1030)

rows = gold_rows(queries_path)
gold = {g["query_text"]: g for g in rows}
queries = gold_queries(rows)
rep = json.load(open(report_path))
hits_pool = collections.defaultdict(list)
recall, errors = {}, {}
by_type = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
for eng, e in rep["engines"].items():
    if eng == ULT:
        continue
    for pq in e["per_query"]:
        if pq["score"] is None:
            continue
        g = gold[pq["query"]]
        gg = g["gold"]
        hit = pq["hit_rank"] is not None
        if hit:
            r = pq["results"][pq["hit_rank"] - 1]
            prov = as_obj(g["query_origin"]).get("provenance", {})
            if gg["field_type"] == "money":
                is_reading = not prose_hit(queries[pq["query"]], r)
                hits_pool["reading" if is_reading else "exact"].append({
                    "kind": "money_reading" if is_reading else "money_exact", "engine": eng, "query": pq["query"], "company": prov.get("entity"),
                    "field": gg["field"], "field_type": "money", "gold": gg["value"], "aliases": gg["aliases"], "rank": pq["hit_rank"],
                    "title": r.get("title"), "url": r["url"], "snippet": r["snippet"]})
            else:
                hits_pool["other"].append({
                    "kind": "other_field", "engine": eng, "query": pq["query"], "company": prov.get("entity"),
                    "field": gg["field"], "field_type": gg["field_type"], "gold": gg["value"], "aliases": gg["aliases"], "rank": pq["hit_rank"],
                    "title": r.get("title"), "url": r["url"], "snippet": r["snippet"]})
        by_type[eng][gg["field_type"]][0] += hit
        by_type[eng][gg["field_type"]][1] += 1
    recall[eng], errors[eng] = e["recall_at_k"], e["search_errors"]
nq = rep["num_queries"]
ult = rep["engines"][ULT]["recall_at_k"]
stamps = sorted(pq["queried_at"] for e in recall for pq in rep["engines"][e]["per_query"] if pq["queried_at"])

hist = load(hist_path)
table_runs = set(json.load(open(pairs_json))["runs"])
fin = [r for r in hist if r["bench"] == "finance" and r["ts"] in table_runs]
t1 = {e: wmean([r for r in fin if r["engine"] == e], "recall") for e in recall}
t1_ult = wmean([r for r in fin if r["engine"] == ULT], "recall")

engines = [e for e in recall if t1.get(e) is not None]
fresh_share = {e: recall[e] / ult for e in engines}
t1_share = {e: t1[e] / t1_ult for e in engines}
tau = tau_b([fresh_share[e] for e in engines], [t1_share[e] for e in engines])
mad = sum(abs(fresh_share[e] - t1_share[e]) for e in engines) / len(engines)
print(f"fresh run: {nq} queries, {len(recall)} engines, searches started {stamps[0]} to {stamps[-1]}")
print(f"ceiling {ult:.3f}; table-1 finance ceiling {t1_ult:.3f}; tau_b shares {tau:.3f}; mean|dshare| {mad:.3f}")
for e in sorted(engines, key=lambda e: -fresh_share[e]):
    money = by_type[e]["money"]
    print(f"  {e:16s} fresh recall {recall[e]:.3f} share {fresh_share[e]:.3f} | table share {t1_share[e]:.3f} | money {money[0]}/{money[1]} | errs {errors[e]}")
print("hit pool:", {k: len(v) for k, v in hits_pool.items()})

sample = []
seen = set()
for kind, cap in (("reading", 10 ** 6), ("exact", 100), ("other", 50)):
    pool = [h for h in hits_pool[kind] if (h["query"], h["url"]) not in seen]
    rng.shuffle(pool)
    for h in pool[:cap]:
        seen.add((h["query"], h["url"]))
        sample.append({"id": len(sample), **h})
rng.shuffle(sample)
for i, s in enumerate(sample):
    s["id"] = i
json.dump(sample, open(f"{out_dir}/dashboard_sample.json", "w"), indent=1)
json.dump({"num_queries": nq, "searches_started": [stamps[0], stamps[-1]], "ceiling": ult, "table1_ceiling": t1_ult, "tau_b_shares": tau, "mean_abs_dshare": mad,
           "engines": {e: {"recall": recall[e], "share": fresh_share[e], "table_share": t1_share[e], "errors": errors[e],
                           "by_type": dict(by_type[e])} for e in engines},
           "pool": {k: len(v) for k, v in hits_pool.items()}, "sample": len(sample)}, open(f"{out_dir}/summary.json", "w"), indent=1)
print("sample", len(sample))
