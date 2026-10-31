import collections
import glob
import json
import os
import random
import sys

site, pairs_json, out_json = sys.argv[1], sys.argv[2], sys.argv[3]
KEEP = "keenable exa google bing brave brave-llmcontext parallel perplexity tavily linkup tinyfish octen ceramic you firecrawl kagi jina context deepseek claude-search chatgpt-search".split()
ACCOUNT = {"perplexity", "exa", "kagi", "parallel", "claude-search"}
BENCHES = {"scholar": ("hfscholar", "scholar.json", "hit"), "news": ("hfnews", "ndcg.json", "ndcg"), "finance": ("hf", "recall.json", "hit"),
           "agentic_rare": ("hfrare", "agentic_rare.json", "ndcg"), "legal": ("hflegal", "legal.json", "hit")}
table_runs = {ts.replace(":", "") for ts in json.load(open(pairs_json))["runs"]}
rng = random.Random(11)


def value(pq, kind):
    if kind == "ndcg":
        return float(pq.get("ndcg") or 0.0)
    return 1.0 if pq.get("hit_rank") is not None else 0.0


runs_by_bench = {}
missing = collections.Counter()
for bench, (folder, report, kind) in BENCHES.items():
    runs = []
    for d in sorted(glob.glob(os.path.join(site, folder, "*"))):
        name = os.path.basename(d)
        if name not in table_runs or not os.path.exists(os.path.join(d, report)):
            if name in table_runs:
                missing[bench] += 1
            continue
        rep = json.load(open(os.path.join(d, report)))
        pqs = {}
        for e in KEEP + ["ultimate"]:
            if e in rep["engines"]:
                p = os.path.join(d, rep["engines"][e].get("per_query_path", ""))
                if os.path.isfile(p):
                    pqs[e] = json.load(open(p))["per_query"]
        if "ultimate" not in pqs or len([e for e in KEEP if e in pqs]) < 21:
            missing[bench] += 1
            continue
        rows = []
        for qi in range(len(pqs["ultimate"])):
            acct_fail = any(pqs[e][qi].get("search_error") is not None for e in KEEP if e in ACCOUNT)
            vals = {}
            for e in KEEP:
                pq = pqs[e][qi]
                failed = pq.get("search_error") is not None
                vals[e] = None if (failed and e in ACCOUNT) else (0.0 if failed else value(pq, kind))
            rows.append({"u": value(pqs["ultimate"][qi], kind), "vals": vals, "acct_fail": acct_fail})
        runs.append(rows)
    runs_by_bench[bench] = runs
    print(bench, "runs used", len(runs), "of", sum(1 for t in table_runs if any(True for _ in [0])) if False else "", "queries", sum(len(r) for r in runs),
          "matched", sum(1 for r in runs for q in r if not q["acct_fail"]), "missing runs", missing[bench], flush=True)


def shares(runs_sel, matched):
    out = collections.defaultdict(dict)
    for bench, runs in runs_sel.items():
        use = [q for r in runs for q in r if not (matched and q["acct_fail"])]
        if not use:
            continue
        u = sum(q["u"] for q in use) / len(use)
        if not u:
            continue
        for e in KEEP:
            vs = [q["vals"][e] for q in use if q["vals"].get(e) is not None]
            if vs:
                out[e][bench] = sum(vs) / len(vs) / u
    return out


def overall(sh):
    return {e: sum(b.values()) / len(b) for e, b in sh.items() if len(b) == len(runs_by_bench)}


base = overall(shares(runs_by_bench, False))
matched = overall(shares(runs_by_bench, True))
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


print("tau_b base vs matched (full window) %.3f" % tau_b(order_b, order_m))
for e in order_b:
    lo, hi = ci(samp_d[e])
    print(f"  {e:17s} base {100*base[e]:5.1f} (rank {order_b.index(e)+1:2d}) matched {100*matched[e]:5.1f} (rank {order_m.index(e)+1:2d}) diff {100*(matched[e]-base[e]):+.1f} [{100*lo:+.1f},{100*hi:+.1f}]")
print("matched support: adjacent separated", adj_sep, "of", len(order_m) - 1, "; all pairs separated", sep_pt, "of", len(pairs), "; Bonferroni", sep_bf)
print("fully separated (Bonferroni):", fully)
print("unseparated:", unsep)
json.dump({"runs": {b: len(r) for b, r in runs_by_bench.items()}, "queries": {b: sum(len(x) for x in r) for b, r in runs_by_bench.items()},
           "matched_queries": {b: sum(1 for x in r for q in x if not q["acct_fail"]) for b, r in runs_by_bench.items()},
           "base": base, "matched": matched, "ci_diff": {e: ci(samp_d[e]) for e in order_m}, "tau_b": tau_b(order_b, order_m),
           "adjacent_separated": adj_sep, "pairs_separated": sep_pt, "pairs_separated_bonferroni": sep_bf, "fully_separated_bonferroni": fully,
           "pairs": pairs, "order_matched": order_m}, open(out_json, "w"), indent=1)
