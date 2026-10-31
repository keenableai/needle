import collections
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import ACCOUNT_SIDE_FAILURES, BENCHES, FAMILIES, NAMES, ULT, load, overall, shares  # noqa: E402

hist, pairs_json, out_path = sys.argv[1:4]
rows = load(hist)
table_runs = set(json.load(open(pairs_json))["runs"])
window = [r for r in rows if r["ts"] in table_runs]
keep = [e for e in sorted({r["engine"] for r in window} - {ULT}) if e not in FAMILIES or e == "brave-llmcontext"]
sh, ult = shares(window, keep)
base = {e: overall(sh, e) for e in keep}
res = {}
for e in keep:
    if e not in ACCOUNT_SIDE_FAILURES:
        continue
    lo_sh, hi_sh = {}, {}
    frac = {}
    for b, m in BENCHES:
        br = [r for r in window if r["bench"] == b and r["engine"] == e]
        scored = sum(r["num_scored"] for r in br)
        issued = sum(r["num_queries"] for r in br)
        f = 1 - scored / issued if issued else 0.0
        frac[b] = f
        v = sh[e][b][0] or 0.0
        lo_sh[b] = ((1 - f) * v) / ult[b]
        hi_sh[b] = ((1 - f) * v + f * ult[b]) / ult[b]
    lo = sum(lo_sh.values()) / len(lo_sh)
    hi = sum(hi_sh.values()) / len(hi_sh)
    res[e] = {"overall": base[e], "excluded_scored_zero": lo, "excluded_scored_as_ceiling": hi, "excluded_fraction": frac}
    print(f"{NAMES.get(e, e):16s} overall {100 * base[e]:.1f}  excluded as zero {100 * lo:.1f}  excluded as ceiling {100 * hi:.1f}  excluded share " + " ".join(f"{b}:{100 * frac[b]:.0f}%" for b, _ in BENCHES))
json.dump(res, open(out_path, "w"), indent=1)
