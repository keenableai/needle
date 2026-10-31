import copy
import os
import sys
from datetime import datetime

sys.path.insert(0, sys.argv[2])
from common import BENCHES, FAMILIES, FMT, ULT, load, overall, shares, weekly_shares, window  # noqa: E402

CUTOFF = datetime(2026, 10, 26, 22, 19)
rows = load(sys.argv[1])
w, end = window(rows, 30)
engines = sorted({r["engine"] for r in w} - {ULT})
keep = [e for e in engines if e not in FAMILIES or e == "brave-llmcontext"]


def adjust(rs, policy):
    out = []
    for r in rs:
        r = copy.copy(r)
        m = dict(BENCHES).get(r["bench"])
        if m is None or r.get(m) is None:
            out.append(r)
            continue
        old = datetime.strptime(r["ts"], FMT) < CUTOFF
        err = r.get("search_errors") or 0
        nq = r.get("num_queries") or r["num_scored"]
        if policy == "excluded" and old and err:
            good = r["num_scored"] - err
            if good <= 0:
                continue
            r[m] = r[m] * r["num_scored"] / good
            r["num_scored"] = good
        if policy == "zero" and not old and err:
            r[m] = r[m] * r["num_scored"] / nq if nq else r[m]
            r["num_scored"] = nq
        out.append(r)
    return out


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


base_sh, _ = shares(w, engines)
base = {e: overall(base_sh, e) for e in keep if overall(base_sh, e) is not None}
names = sorted(base, key=lambda e: -base[e])
for policy in ("excluded", "zero"):
    sh, ult = shares(adjust(w, policy), engines)
    ov = {e: overall(sh, e) for e in names}
    print(f"== policy {policy}: tau_b vs published {tau_b([base[e] for e in names], [ov[e] for e in names]):.3f}; max|d| {max(abs(ov[e]-base[e]) for e in names)*100:.1f} pts")
    ranked = sorted(names, key=lambda e: -ov[e])
    for e in names:
        d = ov[e] - base[e]
        if abs(d) > 0.005:
            print(f"   {e:18s} {base[e]*100:.1f} -> {ov[e]*100:.1f}  rank {names.index(e)+1}->{ranked.index(e)+1}")
    print("   range", f"{min(ov.values())*100:.1f}-{max(ov.values())*100:.1f}")
    wk = weekly_shares(adjust(rows, policy), keep, 8)
    keys = sorted(wk)
    taus = []
    for a, b in zip(keys, keys[1:]):
        common = [e for e in keep if wk[a].get(e) is not None and wk[b].get(e) is not None]
        taus.append(tau_b([wk[a][e] for e in common], [wk[b][e] for e in common]))
    print("   weekly tau range %.2f-%.2f mean %.2f" % (min(taus), max(taus), sum(taus) / len(taus)))
    for e in ("perplexity", "claude-search", "keenable"):
        print("   ", e, [f"{wk[k][e]*100:.0f}" if wk[k].get(e) is not None else "-" for k in keys])
err = {}
for e in names:
    rs = [r for r in w if r["engine"] == e and r["bench"] in dict(BENCHES)]
    err[e] = sum(r.get("search_errors") or 0 for r in rs) / max(1, sum((r.get("num_queries") or 0) for r in rs))
print("error rates", {e: f"{err[e]*100:.1f}" for e in names})
