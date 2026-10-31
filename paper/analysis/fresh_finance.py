import collections
import json
import random
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import ULT, account_side, load, wmean  # noqa: E402
from strict_v2 import match_v2, text_of  # noqa: E402
from needle.finance.models import cues_for  # noqa: E402

queries_path, report_path, hist_path, pairs_json, out_dir = sys.argv[1:6]
K = 5
rng = random.Random(1030)

gold = {}
for line in open(queries_path):
    if line.strip():
        g = json.loads(line)
        gold[g["query_text"]] = g
rep = json.load(open(report_path))
hits_pool = collections.defaultdict(list)
recall, errors, any_hit = {}, {}, collections.defaultdict(bool)
by_type = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
for eng, e in rep["engines"].items():
    if eng == ULT:
        continue
    n = h = err = 0
    for pq in e["per_query"]:
        g = gold[pq["query"]]
        gg = g["gold"]
        if pq.get("search_error") is not None:
            err += 1
            if account_side(pq["search_error"]):
                continue
        n += 1
        hit = False
        if gg["field_type"] == "money":
            aliases = tuple(str(a) for a in gg["aliases"] or [])
            for i, r in enumerate(pq["results"][:K]):
                ok, is_new = match_v2(gg["value"], aliases, text_of(r), cues_for(gg["field"]))
                if ok:
                    hit = True
                    prov = json.loads(g["query_origin"]).get("provenance", {}) if isinstance(g["query_origin"], str) else g["query_origin"].get("provenance", {})
                    hits_pool["reading" if is_new else "exact"].append({
                        "kind": "money_reading" if is_new else "money_exact", "engine": eng, "query": pq["query"], "company": prov.get("entity"),
                        "field": gg["field"], "field_type": "money", "gold": gg["value"], "aliases": gg["aliases"], "rank": i + 1,
                        "title": r.get("title"), "url": r["url"], "snippet": (r.get("snippet") or "")[:2000]})
                    break
        else:
            hit = pq["hit_rank"] is not None
            if hit:
                r = pq["results"][pq["hit_rank"] - 1]
                prov = json.loads(g["query_origin"]).get("provenance", {}) if isinstance(g["query_origin"], str) else g["query_origin"].get("provenance", {})
                hits_pool["other"].append({
                    "kind": "other_field", "engine": eng, "query": pq["query"], "company": prov.get("entity"),
                    "field": gg["field"], "field_type": gg["field_type"], "gold": gg["value"], "aliases": gg["aliases"], "rank": pq["hit_rank"],
                    "title": r.get("title"), "url": r["url"], "snippet": (r.get("snippet") or "")[:2000]})
        by_type[eng][gg["field_type"]][0] += hit
        by_type[eng][gg["field_type"]][1] += 1
        h += hit
        any_hit[pq["query"]] |= hit
    recall[eng], errors[eng] = (h / n if n else None), err
nq = rep["num_queries"]
ult = sum(any_hit.values()) / nq

hist = load(hist_path)
table_runs = set(json.load(open(pairs_json))["runs"])
fin = [r for r in hist if r["bench"] == "finance" and r["ts"] in table_runs]
t1 = {e: wmean([r for r in fin if r["engine"] == e], "recall") for e in recall}
t1_ult = wmean([r for r in fin if r["engine"] == ULT], "recall")


def tau_b(a, b):
    c = d = 0
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            x = (a[i] - a[j]) * (b[i] - b[j])
            c += x > 0
            d += x < 0
    return (c - d) / (c + d)


engines = [e for e in recall if recall[e] is not None and t1.get(e) is not None]
fresh_share = {e: recall[e] / ult for e in engines}
t1_share = {e: t1[e] / t1_ult for e in engines}
tau = tau_b([fresh_share[e] for e in engines], [t1_share[e] for e in engines])
mad = sum(abs(fresh_share[e] - t1_share[e]) for e in engines) / len(engines)
print(f"fresh run: {nq} queries, ceiling {ult:.3f}; table-1 finance ceiling {t1_ult:.3f}; tau_b shares {tau:.3f}; mean|dshare| {mad:.3f}")
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
json.dump(sample, open(f"{out_dir}/sample.json", "w"), indent=1)
for n in range(0, len(sample), 50):
    json.dump([{k: v for k, v in s.items() if k not in ("engine", "kind")} for s in sample[n:n + 50]], open(f"{out_dir}/part{n // 50 + 1}.json", "w"), indent=0, ensure_ascii=False)
json.dump({"num_queries": nq, "ceiling": ult, "table1_ceiling": t1_ult, "tau_b_shares": tau, "mean_abs_dshare": mad,
           "engines": {e: {"recall": recall[e], "share": fresh_share[e], "table_share": t1_share[e], "errors": errors[e],
                           "by_type": {k: v for k, v in by_type[e].items()}} for e in engines},
           "pool": {k: len(v) for k, v in hits_pool.items()}, "sample": len(sample)}, open(f"{out_dir}/summary.json", "w"), indent=1)
print("sample", len(sample), "parts", (len(sample) + 49) // 50)
