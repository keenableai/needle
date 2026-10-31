import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collections
import json
import statistics

from common import ACCOUNT_SIDE_FAILURES, BENCHES, FAMILIES, NAMES, ULT, bootstrap, load, overall, shares, window

hist, out = sys.argv[1], sys.argv[2]
matched = json.load(open(sys.argv[3])) if len(sys.argv) > 3 else None
rows = load(hist)
w, end = window(rows, 30)
engines = sorted({r["engine"] for r in w} - {ULT})
keep0 = [e for e in engines if e not in FAMILIES or e == "brave-llmcontext"]
full_ts = set()
for b, m in BENCHES:
    by_ts = collections.defaultdict(set)
    for r in w:
        if r["bench"] == b and ((r.get(m) is not None and r["num_scored"]) or r["engine"] in ACCOUNT_SIDE_FAILURES):
            by_ts[r["ts"]].add(r["engine"])
    full_ts |= {ts for ts, es in by_ts.items() if all(e in es for e in keep0)}
w = [r for r in w if r["ts"] in full_ts]
sh, ult = shares(w, engines)
ci = bootstrap(w, engines)
keep = [e for e in engines if e not in FAMILIES or e == "brave-llmcontext"]
table = sorted(((overall(sh, e), e) for e in keep if overall(sh, e) is not None), reverse=True)

NOTE = {"keenable": r"\smash{$^\dagger$}", "chatgpt-search": r"\smash{$^\ddagger$}",
        "claude-search": r"\smash{$^{\ddagger\S}$}", "kagi": r"\smash{$^\S$}"}


def fmt(x):
    return "1" if round(x, 3) >= 1 else f"{x:.3f}"[1:]


def signed(x):
    return f"${x:+.2f}$" if abs(x) < 0.05 else f"${x:+.1f}$"


def fail(e):
    rs = [r for r in w if r["engine"] == e]
    pct = 100 * sum(r.get("search_errors") or 0 for r in rs) / max(1, sum(r.get("num_queries") or 0 for r in rs))
    na = r"\textcolor{muted}{--}"
    return (na, f"{pct:.1f}") if e in ACCOUNT_SIDE_FAILURES else (f"{pct:.1f}", na)


def p50(e):
    xs = [r["p50_ms"] for r in w if r["engine"] == e and r["bench"] == "news" and r.get("p50_ms")]
    return f"{round(statistics.median(xs)):,}" if xs else "--"


best = {b: max(sh[e][b][0] for _, e in table) for b, _ in BENCHES}
lines = [r"\textit{ceiling (pooled)} & \textit{100} & & " + " & ".join(rf"\textit{{{fmt(ult[b])}}}" for b, _ in BENCHES) + r" & & & \\"]
for o, e in table:
    lo, hi = ci[e]
    cells = []
    for b, _ in BENCHES:
        v = sh[e][b][0]
        cells.append(rf"\textbf{{{fmt(v)}}}" if round(v, 3) == round(best[b], 3) else fmt(v))
    svc, acc = fail(e)
    lines.append(rf"{NAMES[e]}{NOTE.get(e, '')} & {o * 100:.1f} & \shareci{{{lo * 100:.1f}}}{{{hi * 100:.1f}}} & "
                 + " & ".join(cells) + rf" & {svc} & {acc} & {p50(e)} \\")
open(out, "w").write("\n".join(lines) + "\n")

ci_lines = []
for o, e in table:
    lo, hi = ci[e]
    cols = [NAMES[e], f"{o * 100:.1f}", f"{lo * 100:.1f}--{hi * 100:.1f}"]
    if matched:
        d = 100 * (matched["matched"][e] - matched["base"][e])
        dlo, dhi = (100 * x for x in matched["ci_diff"][e])
        cols += [signed(d), f"{signed(dlo)}, {signed(dhi)}"]
    cols += [fmt(sh[e][b][1]) for b, _ in BENCHES]
    ci_lines.append(" & ".join(cols) + r" \\")
open(out.replace("table_results", "table_ci"), "w").write("\n".join(ci_lines) + "\n")
print(f"window to {end:%d %b %Y}; runs:",
      {b: len({r['ts'] for r in w if r['bench'] == b}) for b, _ in BENCHES},
      "queries:", {b: sum(r['num_queries'] for r in w if r['bench'] == b and r['engine'] == ULT) for b, _ in BENCHES})
