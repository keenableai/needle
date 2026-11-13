import json
import statistics
import sys

from common import BENCHES, NAMES, ULT, bootstrap, load, overall, shares, table_window, window

hist, out = sys.argv[1], sys.argv[2]
matched = json.load(open(sys.argv[3]))
rows = load(hist)
_, end = window(rows, 30)
w, engines, keep = table_window(rows)
sh, ult = shares(w, engines)
ci = bootstrap(w, engines)
table = sorted(((overall(sh, e), e) for e in keep if overall(sh, e) is not None), reverse=True)

NOTE = {"chatgpt-search": r"\smash{$^{\dagger\S}$}",
        "claude-search": r"\smash{$^{\dagger\S}$}", "kagi": r"\smash{$^\S$}",
        "tinyfish": r"\smash{$^\S$}"}


def fmt(x):
    return "1" if round(x, 3) >= 1 else f"{x:.3f}"[1:]


def signed(x):
    return f"${x:+.2f}$" if abs(x) < 0.05 else f"${x:+.1f}$"


def fail(e):
    rs = [r for r in w if r["engine"] == e]
    nq = max(1, sum(r.get("num_queries") or 0 for r in rs))
    return f"{100 * sum(r.get('search_errors') or 0 for r in rs) / nq:.1f}"


def p50(e):
    xs = [r["p50_ms"] for r in w if r["engine"] == e and r["bench"] == "news" and r.get("p50_ms")]
    return f"{round(statistics.median(xs)):,}" if xs else "--"


best = {b: max(sh[e][b][0] for _, e in table) for b, _ in BENCHES}
lines = []
for i, (o, e) in enumerate(table):
    lo, hi = ci[e]
    cells = []
    for b, _ in BENCHES:
        v = sh[e][b][0]
        cells.append(rf"\textbf{{{fmt(v)}}}" if round(v, 3) == round(best[b], 3) else fmt(v))
    share = f"{o * 100:.1f}"
    lines.append(("\\addlinespace[3pt]\n" if i and i % 5 == 0 else "")
                 + rf"{NAMES[e]}{NOTE.get(e, '')} & {share if i else rf'\textbf{{{share}}}'} & \shareci{{{lo * 100:.1f}}}{{{hi * 100:.1f}}} & "
                 + " & ".join(cells) + rf" & {fail(e)} & {p50(e)} \\")
lines.append("\\midrule\n" + r"\textit{Pooled ceiling} & \textit{100} & & " + " & ".join(rf"\textit{{{fmt(ult[b])}}}" for b, _ in BENCHES) + r" & -- & -- \\")
open(out, "w").write("\n".join(lines) + "\n")

ci_lines = []
for o, e in table:
    d = 100 * (matched["matched"][e] - matched["base"][e])
    dlo, dhi = (100 * x for x in matched["ci_diff"][e])
    cols = [NAMES[e], f"{matched['base'][e] * 100:.1f}",
            f"{matched['matched'][e] * 100:.1f}", signed(d), f"{signed(dlo)}, {signed(dhi)}"]
    ci_lines.append(" & ".join(cols) + r" \\")
open(out.replace("table_results", "table_ci"), "w").write("\n".join(ci_lines) + "\n")
print(f"window to {end:%d %b %Y}; runs:",
      {b: len({r['ts'] for r in w if r['bench'] == b}) for b, _ in BENCHES},
      "queries:", {b: sum(r['num_queries'] for r in w if r['bench'] == b and r['engine'] == ULT) for b, _ in BENCHES})
