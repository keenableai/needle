import collections
import glob
import json
import os
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import BENCHES, FAMILIES, ULT, load, overall, shares, window

site, hist, pairs_json = sys.argv[1], sys.argv[2], sys.argv[3]
table_runs = {ts.replace(":", "") for ts in json.load(open(pairs_json))["runs"]}
rows = load(hist)
w, end = window(rows, 30)
w = [r for r in w if r["ts"].replace(":", "") in table_runs]
sh, ult = shares(w, ["kagi", "exa", "claude-search", "google"])
print("history (Table 1) per-bench shares:")
for e in ("kagi", "exa", "claude-search", "google"):
    print(" ", e, {b: round(sh[e][b][1], 3) for b, _ in BENCHES}, "overall %.3f" % overall(sh, e))
kagi_rows = [r for r in w if r["engine"] == "kagi"]
print("kagi history rows", len(kagi_rows), "with errors", sum(1 for r in kagi_rows if r.get("search_errors")), "sum errors", sum(r.get("search_errors") or 0 for r in kagi_rows), "sum num_scored", sum(r["num_scored"] for r in kagi_rows), "sum num_queries", sum(r["num_queries"] for r in kagi_rows))
ex = [r for r in kagi_rows if r.get("search_errors")][:3]
for r in ex:
    print("   sample", {k: r[k] for k in ("bench", "ts", "num_queries", "num_scored", "search_errors") if k in r}, {m: r.get(m) for m in ("ndcg", "recall")})

B = {"scholar": ("hfscholar", "scholar.json", "hit"), "news": ("hfnews", "ndcg.json", "ndcg"), "finance": ("hf", "recall.json", "hit"), "agentic_rare": ("hfrare", "agentic_rare.json", "ndcg"), "legal": ("hflegal", "legal.json", "hit")}
for e in ("kagi",):
    for mode in ("excluded", "zero"):
        per = {}
        for b, (folder, report, kind) in B.items():
            num = den = unum = 0.0
            for d in sorted(glob.glob(os.path.join(site, folder, "*"))):
                name = os.path.basename(d)
                if name not in table_runs or not os.path.exists(os.path.join(d, report)):
                    continue
                rep = json.load(open(os.path.join(d, report)))
                pe = os.path.join(d, rep["engines"].get(e, {}).get("per_query_path", ""))
                pu = os.path.join(d, rep["engines"].get("ultimate", {}).get("per_query_path", ""))
                if not (os.path.isfile(pe) and os.path.isfile(pu)):
                    continue
                qe, qu = json.load(open(pe))["per_query"], json.load(open(pu))["per_query"]
                for a, u in zip(qe, qu):
                    uv = float(u.get("ndcg") or 0.0) if kind == "ndcg" else (1.0 if u.get("hit_rank") is not None else 0.0)
                    if a.get("search_error"):
                        if mode == "excluded":
                            continue
                        v = 0.0
                    else:
                        v = float(a.get("ndcg") or 0.0) if kind == "ndcg" else (1.0 if a.get("hit_rank") is not None else 0.0)
                    num += v
                    unum += uv
                    den += 1
            per[b] = (num / den) / (unum / den) if den and unum else None
        print(f"artifacts kagi failures {mode}:", {b: round(v, 3) if v else None for b, v in per.items()}, "overall %.3f" % (sum(per.values()) / len(per)))
