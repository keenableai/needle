import collections
import json
import sys
from datetime import datetime

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import ACCOUNT_SIDE_FAILURES, BENCHES, FAILURE_EXCLUDED_SINCE, FMT, load, overall, shares

E = "claude-search"
LOW = 0.1
hist, out = sys.argv[1], sys.argv[2]
rows = load(hist)
ACCOUNT_SIDE_FAILURES.discard(E)
zeroed = load(hist)
ACCOUNT_SIDE_FAILURES.add(E)


def weeks(rs):
    byweek = collections.defaultdict(list)
    for r in rs:
        byweek[datetime.strptime(r["ts"], FMT).strftime("%G-W%V")].append(r)
    return byweek


byweek, zweek = weeks(rows), weeks(zeroed)
keys = sorted(byweek)[-9:-1]


def summary(rs):
    sh, ult = shares(rs, [E])
    return {"overall": overall(sh, E),
            "bench": {b: {"metric": sh[E][b][0], "ceiling": ult[b], "share": sh[E][b][1]} for b, _ in BENCHES}}


res = {"weeks": keys}
for k in keys:
    wr = byweek[k]
    mine = [r for r in wr if r["engine"] == E]
    clean_runs = {(r["bench"], r["ts"]) for r in mine if not r.get("search_errors")}
    low_runs = {(r["bench"], r["ts"]) for r in mine if (r.get("search_errors") or 0) <= LOW * r["num_queries"]}
    stats = {}
    for b, _ in BENCHES:
        br = [r for r in mine if r["bench"] == b]
        nq = sum(r.get("num_queries") or 0 for r in br)
        err = sum(r.get("search_errors") or 0 for r in br)
        stats[b] = {"bench_runs": len({r["ts"] for r in wr if r["bench"] == b}), "runs": len(br),
                    "runs_with_errors": sum(1 for r in br if r.get("search_errors")),
                    "runs_over_low": sum(1 for r in br if (r.get("search_errors") or 0) > LOW * r["num_queries"]),
                    "runs_all_failed": sum(1 for r in br if r.get("search_errors") and r["search_errors"] >= r["num_queries"]),
                    "query_runs": nq, "failed": err, "failed_frac": err / nq if nq else None}
    res[k] = {"figure": summary(wr), "runs": stats,
              "zero_error_runs": summary([r for r in wr if (r["bench"], r["ts"]) in clean_runs]),
              "low_error_runs": summary([r for r in wr if (r["bench"], r["ts"]) in low_runs]),
              "failures_zero": summary(zweek[k])}

raw = [json.loads(l) for l in open(hist) if l.strip()]
late = sorted((r["ts"], r["bench"], r["num_queries"], r["num_scored"], r["search_errors"]) for r in raw
              if r["engine"] == E and r.get("search_errors") and datetime.strptime(r["ts"], FMT) >= FAILURE_EXCLUDED_SINCE)
res["rows_after_cutoff_with_errors"] = [dict(zip(("ts", "bench", "num_queries", "num_scored_raw", "search_errors"), t))
                                         for t in late]

days = collections.defaultdict(list)
for r in rows:
    if r["bench"] == "news" and keys[-2] <= datetime.strptime(r["ts"], FMT).strftime("%G-W%V") <= keys[-1]:
        days[r["ts"][:10]].append(r)
res["news_daily"] = {}
for d in sorted(days):
    dr = days[d]
    mine = [r for r in dr if r["engine"] == E]
    ok = {r["ts"] for r in mine if not r.get("search_errors")}
    sh, _ = shares(dr, [E])
    shc, _ = shares([r for r in dr if r["ts"] in ok], [E])
    res["news_daily"][d] = {"runs": len(mine), "clean_runs": len(ok),
                            "failed_frac": sum(r.get("search_errors") or 0 for r in mine) / max(1, sum(r["num_queries"] for r in mine)),
                            "share": sh[E]["news"][1], "share_clean_runs": shc[E]["news"][1]}

pct = lambda v: "  -  " if v is None else "%5.1f" % (100 * v)
print("week      fig   clean  low   zero | " + " ".join("%-22s" % b for b, _ in BENCHES))
for k in keys:
    w = res[k]
    cells = []
    for b, _ in BENCHES:
        s = w["runs"][b]
        cells.append("%s %3d/%-3d f%s" % (pct(w["figure"]["bench"][b]["share"]), s["runs"], s["bench_runs"], pct(s["failed_frac"])))
    print(k, pct(w["figure"]["overall"]), pct(w["zero_error_runs"]["overall"]), pct(w["low_error_runs"]["overall"]), pct(w["failures_zero"]["overall"]), "|",
          " ".join("%-22s" % c for c in cells))
for lab in ("figure", "zero_error_runs", "low_error_runs", "failures_zero"):
    print("%-16s" % lab, " ".join(pct(res[k][lab]["overall"]) for k in keys[2:]), "|",
          " ".join("%s:%s" % (b[:3], " ".join(pct(res[k][lab]["bench"][b]["share"]) for k in keys[2:])) for b, _ in BENCHES))
for d, v in res["news_daily"].items():
    print(d, "news runs %2d clean %2d failed %s share %s clean-run share %s" % (
        v["runs"], v["clean_runs"], pct(v["failed_frac"]), pct(v["share"]), pct(v["share_clean_runs"])))
for t in res["rows_after_cutoff_with_errors"]:
    print("after cutoff", t)
json.dump(res, open(out, "w"), indent=1)
