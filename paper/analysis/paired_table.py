import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import NAMES  # noqa: E402

out = sys.argv[1]
files = dict(zip(sys.argv[2::2], sys.argv[3::2]))
data = {b: json.load(open(p))["engines"] for b, p in files.items()}
COLS = [("finance", "filing", ("quoted", "site", "date")), ("legal", "caselaw", ("quoted", "site", "date")), ("legal", "code", ("quoted", "site"))]
cols = [(b, bk, vs) for b, bk, vs in COLS if b in data]
first = data.get("finance", data[next(iter(data))])
engines = sorted({e for d in data.values() for e in d}, key=lambda e: -(first.get(e, {}).get("filing", {}).get("plain") or 0))
HEAD = {"quoted": "quoted", "site": r"\texttt{site:}", "date": "dates"}


def p(x):
    return "1" if round(x, 2) >= 1 else f"{x:.2f}"[1:]


def cell(d, v):
    if v not in d:
        return "--"
    m, lo, hi = d[v]["mean"], d[v]["lo"], d[v]["hi"]
    s = "0" if abs(m) < 0.005 else f"${m:+.2f}$".replace("0.", ".")
    return s if lo > 0 or hi < 0 else rf"\textcolor{{muted}}{{{s}}}"


lines = [r"\begin{tabular}{@{}l" + "".join("r" * (1 + len(vs)) for _, _, vs in cols) + "@{}}", r"\toprule"]
title = {"filing": "SEC filings", "caselaw": "Caselaw captions", "code": "CFR sections"}
head1 = [""]
rules = []
start = 2
for b, bk, vs in cols:
    n = first if b == "finance" else data[b]
    targets = n.get(engines[0], {}).get(bk, {}).get("n", "?")
    head1.append(rf"\multicolumn{{{1 + len(vs)}}}{{c}}{{{title[bk]} ({targets} targets)}}")
    rules.append(rf"\cmidrule(lr){{{start}-{start + len(vs)}}}")
    start += 1 + len(vs)
lines.append(" & ".join(head1) + r" \\")
lines.append("".join(rules))
head2 = ["Engine"] + [h for _, _, vs in cols for h in ["plain", *[HEAD[v] for v in vs]]]
lines.append(" & ".join(head2) + r" \\")
lines.append(r"\midrule")
for e in engines:
    row = [NAMES.get(e, e)]
    for b, bk, vs in cols:
        d = data[b].get(e, {}).get(bk)
        if not d or d.get("plain") is None:
            row += ["--"] * (1 + len(vs))
            continue
        row.append(p(d["plain"]))
        row += [cell(d, v) for v in vs]
    lines.append(" & ".join(row) + r" \\")
lines += [r"\bottomrule", r"\end{tabular}"]
open(out, "w").write("\n".join(lines) + "\n")
print("wrote", out, "engines", len(engines), "cols", [(b, bk) for b, bk, _ in cols])
