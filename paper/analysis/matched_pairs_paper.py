import collections
import glob
import json
import os
import random
import sys

here = os.path.dirname(os.path.abspath(__file__))
site, pairs_json, hist, src, out_json = sys.argv[1:6]
sys.path.insert(0, here)
sys.path.insert(0, src)
from common import load  # noqa: E402
from common import overall as c_overall, shares as c_shares  # noqa: E402
from needle.shared.search.errors import account_side  # noqa: E402
from strict_v2 import finance_run  # noqa: E402

KEEP = "keenable exa google bing brave brave-llmcontext parallel perplexity tavily linkup tinyfish octen ceramic you firecrawl kagi jina context deepseek claude-search chatgpt-search".split()
BENCHES = {"scholar": ("hfscholar", "scholar.json", "recall"), "news": ("hfnews", "ndcg.json", "ndcg"), "finance": ("hf", "recall.json", "recall"),
           "agentic_rare": ("hfrare", "agentic_rare.json", "ndcg"), "legal": ("hflegal", "legal.json", "recall")}
pairs_ref = json.load(open(pairs_json))
table_runs = set(pairs_ref["runs"])
rng = random.Random(11)


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
            for q, c in zip(pq, ceiling)]


def is_account(q):
    return q["search_error"] is not None and account_side(q["search_error"])


hist_adj = {(r["bench"], r["ts"], r["engine"]): r for r in load(hist) if r["ts"] in table_runs}

runs_by_bench = {}
used_ts = collections.defaultdict(set)
check = collections.Counter()
mismatch = []
for bench, (folder, report, m) in BENCHES.items():
    runs = []
    for d in sorted(glob.glob(os.path.join(site, folder, "*"))):
        name = os.path.basename(d)
        ts = name[:13] + ":" + name[13:15] + "Z"
        if ts not in table_runs or not os.path.exists(os.path.join(d, report)):
            continue
        rep = json.load(open(os.path.join(d, report)))
        pqs = {e: json.load(open(os.path.join(d, v["per_query_path"])))["per_query"] for e, v in rep["engines"].items()
               if os.path.isfile(os.path.join(d, v.get("per_query_path", "")))}
        if "ultimate" not in pqs or any(e not in pqs for e in KEEP):
            check[f"{bench}: run skipped, per-query files missing"] += 1
            continue
        if bench == "finance":
            pqs = {e: v["per_query"] for e, v in finance_run(d)[0]["engines"].items()}
        ult_hits = collections.defaultdict(bool)
        ceiling = [q["ndcg"] is not None for q in pqs["ultimate"]] if m == "ndcg" else [True] * len(pqs["ultimate"])
        engines = [e for e in pqs if e != "ultimate"] + ["ultimate"] if bench in ("finance", "legal") else KEEP + ["ultimate"]
        vals = {}
        for e in engines:
            v = values(bench, e, pqs[e], ult_hits, ceiling)
            if bench in ("finance", "legal") and e != "ultimate":
                for q, x in zip(pqs[e], v):
                    ult_hits[q["query"]] |= bool(x)
            if e not in KEEP and e != "ultimate":
                continue
            acc = sum(map(is_account, pqs[e]))
            svc = sum(q["search_error"] is not None for q in pqs[e]) - acc
            a = hist_adj.get((bench, ts, e))
            n = sum(x is not None for x in v)
            mean = sum(x for x in v if x is not None) / n if n else None
            ok = (a is not None and n == a["num_scored"] and abs((mean or 0) - (a.get(m) or 0)) < 1e-9
                  and acc == a.get("account_errors", 0) and svc == a.get("service_errors", 0))
            check[f"{bench}: row reproduced {ok}"] += 1
            if not ok:
                mismatch.append((bench, ts, e, n, mean, acc, svc, a and a["num_scored"], a and a.get(m), a and a.get("account_errors"), a and a.get("service_errors")))
            vals[e] = v
        nq = len(pqs["ultimate"])
        assert all(len(vals[e]) == nq and all(pqs[e][i]["query"] == pqs["ultimate"][i]["query"] for i in range(nq)) for e in KEEP)
        acct = [any(is_account(pqs[e][i]) for e in KEEP) for i in range(nq)]
        agg = {}
        for e in KEEP + ["ultimate"]:
            bs = [x for x in vals[e] if x is not None]
            ms = [x for x, f in zip(vals[e], acct) if x is not None and not f]
            agg[e] = (sum(bs), len(bs), sum(ms), len(ms))
        runs.append({"ts": ts, "agg": agg, "queries": nq, "matched": nq - sum(acct)})
        used_ts[bench].add(ts)
    runs_by_bench[bench] = runs
for k, v in sorted(check.items()):
    print(k, v)
for x in mismatch[:20]:
    print("  row mismatch", x)


def shares(runs_sel, matched):
    out = collections.defaultdict(dict)
    for bench, runs in runs_sel.items():
        tot = collections.defaultdict(lambda: [0.0, 0])
        for r in runs:
            for e, (bs, bn, ms, mn) in r["agg"].items():
                tot[e][0] += ms if matched else bs
                tot[e][1] += mn if matched else bn
        if not tot["ultimate"][1] or not tot["ultimate"][0]:
            continue
        u = tot["ultimate"][0] / tot["ultimate"][1]
        for e in KEEP:
            if tot[e][1]:
                out[e][bench] = tot[e][0] / tot[e][1] / u
    return out


def overall(sh):
    return {e: sum(b.values()) / len(b) for e, b in sh.items() if len(b) == len(runs_by_bench)}


base = overall(shares(runs_by_bench, False))
matched = overall(shares(runs_by_bench, True))
table1 = pairs_ref["base"]
sub_rows = [r for r in hist_adj.values() if r["ts"] in used_ts[r["bench"]]]
sh_sub, _ = c_shares(sub_rows, KEEP)
table1_sub = {e: c_overall(sh_sub, e) for e in KEEP}
dev = {e: 100 * (base[e] - table1[e]) for e in KEEP}
dev_sub = {e: 100 * (base[e] - table1_sub[e]) for e in KEEP}
print("runs used", {b: len(r) for b, r in runs_by_bench.items()}, "of", {b: len({t for (bb, t, _) in hist_adj if bb == b}) for b in BENCHES})
print("max |per-query base - Table 1| %.3f points (%s); same runs: %.6f" % (max(abs(x) for x in dev.values()), max(dev, key=lambda e: abs(dev[e])), max(abs(x) for x in dev_sub.values())))

order_t1 = pairs_ref["order"]
order_b = sorted(base, key=lambda e: -base[e])
order_m = sorted(matched, key=lambda e: -matched[e])
N = 1000
samp_m = collections.defaultdict(list)
samp_d = collections.defaultdict(list)
for _ in range(N):
    sel = {b: [runs[rng.randrange(len(runs))] for _ in runs] for b, runs in runs_by_bench.items()}
    m1 = overall(shares(sel, True))
    b1 = overall(shares(sel, False))
    for e in order_m:
        samp_m[e].append(m1.get(e, float("nan")))
        samp_d[e].append(m1.get(e, float("nan")) - b1.get(e, float("nan")))


def ci(xs):
    v = sorted(x for x in xs if x == x)
    return v[int(.025 * len(v))], v[int(.975 * len(v))]


Z = 3.683
pairs = {}
sep_pt = sep_bf = 0
unsep = []
for i, a in enumerate(order_m):
    for b in order_m[i + 1:]:
        d = [x - y for x, y in zip(samp_m[a], samp_m[b]) if x == x and y == y]
        lo, hi = ci(d)
        mu = sum(d) / len(d)
        sd = (sum((x - mu) ** 2 for x in d) / (len(d) - 1)) ** 0.5
        diff = matched[a] - matched[b]
        pt = lo > 0
        bf = diff - Z * sd > 0
        sep_pt += pt
        sep_bf += bf
        if not pt:
            unsep.append((a, b, round(100 * diff, 1)))
        pairs[f"{a}|{b}"] = {"diff": diff, "lo": lo, "hi": hi, "sep": pt, "sep_bonferroni": bf}
adj_sep = sum(pairs[f"{a}|{b}"]["sep"] for a, b in zip(order_m, order_m[1:]))
fully = [e for e in order_m if all(pairs.get(f"{e}|{f}", pairs.get(f"{f}|{e}"))["sep_bonferroni"] for f in order_m if f != e)]


def tau_b(a, b):
    c = d = 0
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            x = (a.index(a[i]) - a.index(a[j])) * (b.index(a[i]) - b.index(a[j]))
            c += x > 0
            d += x < 0
    return (c - d) / (c + d)


print("tau_b matched vs per-query base %.3f; vs Table 1 order %.3f; base vs Table 1 order %.3f" % (tau_b(order_b, order_m), tau_b(order_t1, order_m), tau_b(order_t1, order_b)))
for e in order_t1:
    lo, hi = ci(samp_d[e])
    print(f"  {e:17s} T1 {100*table1[e]:5.2f} base {100*base[e]:5.2f} (rank {order_b.index(e)+1:2d}) matched {100*matched[e]:5.2f} (rank {order_m.index(e)+1:2d}) diff {100*(matched[e]-base[e]):+.1f} [{100*lo:+.1f},{100*hi:+.1f}]")
print("matched support: adjacent separated", adj_sep, "of", len(order_m) - 1, "; all pairs separated", sep_pt, "of", len(pairs), "; Bonferroni", sep_bf)
print("fully separated (Bonferroni):", fully)
print("unseparated:", unsep)
json.dump({"scorer": "production (finance money rematched by scripts/backfill_scores.rematch_money; other benches use the stored per-query scores; account-side failures by needle.shared.search.errors.account_side excluded, service-side failures zero, on nDCG only where the ceiling is non-empty)",
           "runs": {b: len(r) for b, r in runs_by_bench.items()}, "queries": {b: sum(x["queries"] for x in r) for b, r in runs_by_bench.items()},
           "matched_queries": {b: sum(x["matched"] for x in r) for b, r in runs_by_bench.items()}, "row_check": dict(check), "row_mismatches": mismatch,
           "table1": table1, "table1_same_runs": table1_sub, "base_minus_table1_points": dev,
           "base": base, "matched": matched, "ci_diff": {e: ci(samp_d[e]) for e in order_m}, "tau_b": tau_b(order_b, order_m), "tau_b_table1_order": tau_b(order_t1, order_m),
           "adjacent_separated": adj_sep, "pairs_separated": sep_pt, "pairs_separated_bonferroni": sep_bf, "fully_separated_bonferroni": fully,
           "pairs": pairs, "order_matched": order_m, "order_base": order_b}, open(out_json, "w"), indent=1)
