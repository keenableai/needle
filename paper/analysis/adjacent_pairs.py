import collections
import json
import random
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import BENCHES, FAMILIES, NAMES, ULT, account_errors, load, overall, shares, window

hist, out = sys.argv[1], sys.argv[2]
rows = load(hist)
w, end = window(rows, 30)
engines_all = sorted({r["engine"] for r in w} - {ULT})
keep0 = [e for e in engines_all if e not in FAMILIES or e == "brave-llmcontext"]
full_ts = set()
for b, m in BENCHES:
    by_ts = collections.defaultdict(set)
    for r in w:
        if r["bench"] == b and ((r.get(m) is not None and r["num_scored"]) or account_errors(r)):
            by_ts[r["ts"]].add(r["engine"])
    full_ts |= {ts for ts, es in by_ts.items() if all(e in es for e in keep0)}
w = [r for r in w if r["ts"] in full_ts]
engines = keep0
sh, _ = shares(w, engines)
order = sorted([e for e in engines if overall(sh, e) is not None], key=lambda e: -overall(sh, e))
base = {e: overall(sh, e) for e in order}

rnd = random.Random(1926)
cluster = sys.argv[3] if len(sys.argv) > 3 else "run"
runs_by_bench = {}
for b, m in BENCHES:
    byts = collections.defaultdict(list)
    for r in w:
        if r["bench"] == b and r.get(m) is not None and r["num_scored"]:
            byts[r["ts"][:10] if cluster == "day" else r["ts"]].append((r["engine"], r[m], r["num_scored"]))
    runs_by_bench[b] = list(byts.values())

samples = collections.defaultdict(list)
N = 2000
for _ in range(N):
    acc = collections.defaultdict(float)
    accn = collections.Counter()
    for b, _m in BENCHES:
        runs = runs_by_bench[b]
        sums = collections.defaultdict(float)
        wts = collections.defaultdict(float)
        for _k in range(len(runs)):
            for e, v, wt in runs[rnd.randrange(len(runs))]:
                sums[e] += v * wt
                wts[e] += wt
        if not wts[ULT] or not sums[ULT]:
            continue
        u = sums[ULT] / wts[ULT]
        for e in order:
            if wts[e]:
                acc[e] += sums[e] / wts[e] / u
                accn[e] += 1
    for e in order:
        samples[e].append(acc[e] / accn[e] if accn[e] else float("nan"))


def ci(diffs):
    d = sorted(x for x in diffs if x == x)
    return d[int(.025 * len(d))], d[int(.975 * len(d))]


pairs = []
for a, b in zip(order, order[1:]):
    diffs = [x - y for x, y in zip(samples[a], samples[b])]
    lo, hi = ci(diffs)
    pairs.append({"a": a, "b": b, "diff": base[a] - base[b], "lo": lo, "hi": hi, "separated": lo > 0})
    print(f"{NAMES[a][:16]:16s} - {NAMES[b][:16]:16s} diff {100*(base[a]-base[b]):+5.1f} ci [{100*lo:+5.1f},{100*hi:+5.1f}] {'SEP' if lo > 0 else 'overlap'}")
print("adjacent pairs", len(pairs), "separated", sum(p["separated"] for p in pairs))

sep_matrix = {}
for i, a in enumerate(order):
    for b in order[i + 1:]:
        lo, hi = ci([x - y for x, y in zip(samples[a], samples[b])])
        sep_matrix[f"{a}|{b}"] = {"diff": base[a] - base[b], "lo": lo, "hi": hi, "separated": lo > 0}
Z = 3.683
for k, v in sep_matrix.items():
    a, b = k.split("|")
    d = [x - y for x, y in zip(samples[a], samples[b])]
    d = [x for x in d if x == x]
    mu = sum(d) / len(d)
    sd = (sum((x - mu) ** 2 for x in d) / (len(d) - 1)) ** 0.5
    v["sd"] = sd
    v["separated_bonferroni"] = (v["diff"] - Z * sd) > 0
print("Bonferroni (z=3.68, 210 tests) separated:", sum(v["separated_bonferroni"] for v in sep_matrix.values()))
fully = [e for e in order if all(sep_matrix.get(f"{e}|{f}", sep_matrix.get(f"{f}|{e}"))["separated_bonferroni"] for f in order if f != e)]
print("separated from every other engine (Bonferroni):", fully)
fully_pt = [e for e in order if all(sep_matrix.get(f"{e}|{f}", sep_matrix.get(f"{f}|{e}"))["separated"] for f in order if f != e)]
print("separated from every other engine (pointwise):", fully_pt)
unsep = [k for k, v in sep_matrix.items() if not v["separated"]]
print("all pairs", len(sep_matrix), "not separated", len(unsep))
for k in unsep:
    a, b = k.split("|")
    print("   not separated:", NAMES[a], "vs", NAMES[b], "diff %+.1f" % (100 * sep_matrix[k]["diff"]))
json.dump({"order": order, "base": base, "adjacent": pairs, "all_pairs": sep_matrix, "runs": sorted(full_ts), "cluster": cluster, "fully_separated_bonferroni": fully, "fully_separated_pointwise": fully_pt}, open(out, "w"), indent=1)
