import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import NAMES  # noqa: E402

reading_json, legal_json, out = sys.argv[1:4]
rd = json.load(open(reading_json))["engines"]
lg = {r["engine"]: r for r in json.load(open(legal_json))}
order = sorted(rd, key=lambda e: rd[e]["rank"])


def p(x):
    return "1" if round(x, 2) >= 1 else f"{x:.2f}"[1:]


lines = [r"\begin{tabular}{@{}lrrrrrrrr@{}}", r"\toprule",
         r" & \multicolumn{4}{c}{Finance: table-reading hits} & \multicolumn{4}{c}{Caselaw: identity of the hit} \\",
         r"\cmidrule(lr){2-5}\cmidrule(lr){6-9}",
         r"Engine & $n$ & confirmed & recall loss & rank & own share & any-host R@5 & $\times$ pooled & $\times$ own \\",
         r"\midrule"]
for e in order:
    r = rd[e]
    l = lg.get(e)
    rank = f"{r['rank']}" if r["rank"] == r["rank_corrected"] else f"{r['rank']} $\\to$ {r['rank_corrected']}"
    case = [p(l["own_fraction"]), p(l["recall"]), p(l["target_pooled"]), p(l["target_own"])] if l else ["--"] * 4
    lines.append(" & ".join([NAMES.get(e, e), str(r["reading_hits"]), p(r["precision_used"]),
                             f"{100 * r['finance_recall_drop']:.1f}", rank, *case]) + r" \\")
lines += [r"\bottomrule", r"\end{tabular}"]
open(out, "w").write("\n".join(lines) + "\n")
print("wrote", out, len(order), "engines")
