import collections
import itertools
import json
import sys
from datetime import datetime

from common import FAMILIES, FMT, ULT, load, overall, shares
from scipy.stats import kendalltau

hist, out = sys.argv[1], sys.argv[2]
rows = load(hist)
byweek = collections.defaultdict(list)
for r in rows:
    byweek[datetime.strptime(r["ts"], FMT).strftime("%G-W%V")].append(r)
keys = sorted(byweek)[-9:-1]


def table1(e):
    return e not in FAMILIES or e == "brave-llmcontext"


def adjacent(wk, panel=None):
    taus = []
    for a, b in itertools.pairwise(keys):
        common = sorted((set(wk[a]) & set(wk[b])) if panel is None else panel)
        taus.append({"weeks": [a, b], "n": len(common),
                     "tau_b": kendalltau([wk[a][e] for e in common], [wk[b][e] for e in common]).statistic})
    vals = [t["tau_b"] for t in taus]
    return {"pairs": taus, "min": min(vals), "max": max(vals), "mean": sum(vals) / len(vals)}


res = {"weeks": keys}
for name, keep in (("table1", table1), ("all_configs", lambda e: True)):
    wk = {}
    for k in keys:
        engs = sorted(e for e in {r["engine"] for r in byweek[k]} - {ULT} if keep(e))
        sh, _ = shares(byweek[k], engs)
        wk[k] = {e: overall(sh, e) for e in engs if overall(sh, e) is not None}
    panel = sorted(set.intersection(*(set(wk[k]) for k in keys)))
    res[name] = {
        "pool": {k: len(wk[k]) for k in keys},
        "leader": {k: max(wk[k], key=wk[k].get) for k in keys},
        "panel": panel,
        "panel_leader": {k: max(panel, key=wk[k].get) for k in keys},
        "adjacent": adjacent(wk),
        "adjacent_panel": adjacent(wk, panel),
        "shares": wk,
    }
    r = res[name]
    print(name, "pool", list(r["pool"].values()), "leaders", sorted(set(r["leader"].values())), "panel", len(panel))
    for lab in ("adjacent", "adjacent_panel"):
        a = r[lab]
        print(f"  {lab:<15}", " ".join(f"{t['tau_b']:.3f}" for t in a["pairs"]),
              f"range {a['min']:.3f}-{a['max']:.3f} mean {a['mean']:.3f}")
json.dump(res, open(out, "w"), indent=1)
