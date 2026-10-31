import collections
import random
import sys
from datetime import datetime

sys.path.insert(0, sys.argv[2])
from common import ACCOUNT_SIDE_FAILURES, BENCHES, FAMILIES, FMT, ULT, load, overall, shares, window  # noqa: E402

rows = load(sys.argv[1])
w, end = window(rows, 30)
engines = sorted({r["engine"] for r in w} - {ULT})
keep = [e for e in engines if e not in FAMILIES or e == "brave-llmcontext"]


def tau_b(a, b):
    n = len(a); c = d = ta = tb = 0
    for i in range(n):
        for j in range(i + 1, n):
            x, y = a[i] - a[j], b[i] - b[j]
            if x == 0 and y == 0:
                continue
            if x == 0:
                ta += 1
            elif y == 0:
                tb += 1
            elif x * y > 0:
                c += 1
            else:
                d += 1
    return (c - d) / (((c + d + ta) * (c + d + tb)) ** 0.5)


sh, _ = shares(w, engines)
base = {e: overall(sh, e) for e in keep if overall(sh, e) is not None}
names = sorted(base, key=lambda e: -base[e])

common = []
dropped = collections.Counter()
for b, m in BENCHES:
    by_ts = collections.defaultdict(set)
    for r in w:
        if r["bench"] == b and ((r.get(m) is not None and r["num_scored"]) or r["engine"] in ACCOUNT_SIDE_FAILURES):
            by_ts[r["ts"]].add(r["engine"])
    full = {ts for ts, es in by_ts.items() if all(e in es for e in names)}
    dropped[b] = (len(by_ts) - len(full), len(by_ts))
    common += [r for r in w if r["bench"] == b and r["ts"] in full]
sh_c, _ = shares(common, engines)
ov = {e: overall(sh_c, e) for e in names}
print("runs dropped per bench (dropped, total):", dict(dropped))
print("common-support tau_b vs Table 1: %.3f  max|d| %.1f pts" % (tau_b([base[e] for e in names], [ov[e] for e in names]), max(abs(ov[e] - base[e]) for e in names) * 100))
ranked = sorted(names, key=lambda e: -ov[e])
for e in names:
    if abs(ov[e] - base[e]) > 0.005 or ranked.index(e) != names.index(e):
        print(f"   {e:18s} {base[e]*100:.1f} -> {ov[e]*100:.1f}  rank {names.index(e)+1}->{ranked.index(e)+1}")

byweek = collections.defaultdict(list)
for r in rows:
    byweek[datetime.strptime(r["ts"], FMT).strftime("%G-W%V")].append(r)
keys = sorted(byweek)[-9:-1]
present = None
for k in keys:
    es = {r["engine"] for r in byweek[k]} & set(keep)
    present = es if present is None else present & es
cohort = sorted(present)
print("fixed cohort over 8 weeks:", len(cohort), cohort)
wk = {}
for k in keys:
    rs = [r for r in byweek[k] if r["engine"] in cohort or r["engine"] == ULT]
    s2, _ = shares(rs, cohort)
    wk[k] = {e: overall(s2, e) for e in cohort}
taus = []
for a, b in zip(keys, keys[1:]):
    cm = [e for e in cohort if wk[a].get(e) is not None and wk[b].get(e) is not None]
    taus.append(tau_b([wk[a][e] for e in cm], [wk[b][e] for e in cm]))
print("fixed-cohort weekly tau range %.2f-%.2f mean %.2f" % (min(taus), max(taus), sum(taus) / len(taus)))
for e in ("keenable", "perplexity", "exa", "google"):
    print("  ", e, [f"{wk[k][e]*100:.0f}" for k in keys])

rnd = random.Random(1926)
runs_by_bench = {}
days_by_bench = {}
for b, m in BENCHES:
    byts = collections.defaultdict(list)
    for r in w:
        if r["bench"] == b and r.get(m) is not None and r["num_scored"]:
            byts[r["ts"]].append((r["engine"], r[m], r["num_scored"]))
    runs_by_bench[b] = list(byts.values())
    byday = collections.defaultdict(list)
    for ts, items in byts.items():
        byday[ts[:10]].extend(items)
    days_by_bench[b] = list(byday.values())


def boot(groups_by_bench, n=1000):
    samples = collections.defaultdict(list)
    for _ in range(n):
        acc = collections.defaultdict(float); accn = collections.Counter()
        for b, _m in BENCHES:
            groups = groups_by_bench[b]
            sums = collections.defaultdict(float); wts = collections.defaultdict(float)
            for _k in range(len(groups)):
                for e, v, wt in groups[rnd.randrange(len(groups))]:
                    sums[e] += v * wt; wts[e] += wt
            if not wts[ULT] or not sums[ULT]:
                continue
            u = sums[ULT] / wts[ULT]
            for e in names:
                if wts[e]:
                    acc[e] += sums[e] / wts[e] / u; accn[e] += 1
        for e in names:
            if accn[e]:
                samples[e].append(acc[e] / accn[e])
    def pct(xs, p):
        xs = sorted(xs); return xs[min(len(xs) - 1, int(p * len(xs)))]
    return {e: (pct(v, .025), pct(v, .975)) for e, v in samples.items()}


ci_run = boot(runs_by_bench)
ci_day = boot(days_by_bench)
wr = sum(ci_run[e][1] - ci_run[e][0] for e in names) / len(names)
wd = sum(ci_day[e][1] - ci_day[e][0] for e in names) / len(names)
print("mean CI width run-level %.1f pts, day-block %.1f pts (x%.2f)" % (wr * 100, wd * 100, wd / wr))
overl_run = sum(1 for a, b in zip(names, names[1:]) if ci_run[a][0] <= ci_run[b][1])
overl_day = sum(1 for a, b in zip(names, names[1:]) if ci_day[a][0] <= ci_day[b][1])
print("adjacent pairs with overlapping CIs: run-level", overl_run, "day-block", overl_day, "of", len(names) - 1)
print("day-block CIs:", {e: (round(ci_day[e][0] * 100, 1), round(ci_day[e][1] * 100, 1)) for e in names})
