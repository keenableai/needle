import collections
import glob
import json
import math
import os
import random
import re
import sys
from datetime import datetime

here = os.path.dirname(os.path.abspath(__file__))
site, pairs_json, hist, src, out_json = sys.argv[1:6]
sys.path.insert(0, here)
sys.path.insert(0, src)
from common import ACCOUNT_SIDE_FAILURES, FAILURE_EXCLUDED_SINCE, FMT, load  # noqa: E402
from common import overall as c_overall, shares as c_shares  # noqa: E402
from needle.finance.models import cues_for  # noqa: E402
from needle.shared.metrics import GAIN, normalize_url  # noqa: E402
from strict_v2 import K, host_ok, match_v2, text_of  # noqa: E402

KEEP = "keenable exa google bing brave brave-llmcontext parallel perplexity tavily linkup tinyfish octen ceramic you firecrawl kagi jina context deepseek claude-search chatgpt-search".split()
ACCOUNT = {"perplexity", "exa", "kagi", "parallel", "claude-search"}
BENCHES = {"scholar": ("hfscholar", "scholar.json", "recall"), "news": ("hfnews", "ndcg.json", "ndcg"), "finance": ("hf", "recall.json", "recall"),
           "agentic_rare": ("hfrare", "agentic_rare.json", "ndcg"), "legal": ("hflegal", "legal.json", "recall")}
SITE_RE = re.compile(r"site:(\S+)")
pairs_ref = json.load(open(pairs_json))
table_runs = set(pairs_ref["runs"])
rng = random.Random(11)


def site_ok(pq, url):
    m = SITE_RE.search(pq["query"])
    return not m or host_ok(url, m.group(1).lower().strip('"'))


def finance_hit(pq, g):
    if g is None:
        return 0.0
    gg = g["gold"]
    if gg["field_type"] != "money":
        return float(pq["hit_rank"] is not None and site_ok(pq, pq["results"][pq["hit_rank"] - 1]["url"]))
    aliases = tuple(str(a) for a in gg["aliases"] or [])
    return float(any(match_v2(gg["value"], aliases, text_of(r), cues_for(gg["field"]))[0] and site_ok(pq, r["url"]) for r in pq["results"][:K]))


def legal_hit(pq):
    return float(pq.get("hit_rank") is not None and site_ok(pq, pq["results"][pq["hit_rank"] - 1]["url"]))


def rare_value(pq):
    if pq["search_error"] is not None:
        return 0.0
    if pq["ndcg"] is None or pq["ndcg"] == 0 or not re.search(r"\bsite:", pq["query"].lower()):
        return pq["ndcg"]
    idcg = pq["dcg"] / pq["ndcg"]
    seen, pen = set(), []
    for r, rating in zip(pq["results"], pq["ratings"]):
        u = normalize_url(r["url"])
        pen.append(0 if (u in seen or rating is None) else rating)
        seen.add(u)
    return sum(GAIN.get(x, 0.0) / math.log2(i + 2) for i, x in enumerate(pen[:5])) / idcg if idcg else pq["ndcg"]


def raw_values(bench, eng, pq, rep_e, gold, ult_hits):
    errs = [q.get("search_error") is not None for q in pq]
    if bench == "news":
        return [q.get("ndcg") for q in pq], errs
    if bench == "agentic_rare":
        return [rare_value(q) for q in pq], errs
    if bench == "scholar":
        counted = rep_e["num_scored"] == len(pq)
        return [(0.0 if counted else None) if e else float(q["hit_rank"] is not None) for q, e in zip(pq, errs)], errs
    if eng == "ultimate":
        return [float(ult_hits[q["query"]]) for q in pq], [False] * len(pq)
    if bench == "finance":
        return [0.0 if e else finance_hit(q, gold.get(q["query"])) for q, e in zip(pq, errs)], errs
    return [0.0 if e else legal_hit(q) for q, e in zip(pq, errs)], errs


def apply_policy(ts, eng, vals, errs):
    n, err, nq = sum(v is not None for v in vals), sum(errs), len(vals)
    if not err or not nq or not n:
        return vals
    old_policy = datetime.strptime(ts, FMT) < FAILURE_EXCLUDED_SINCE
    if eng in ACCOUNT_SIDE_FAILURES:
        return [None if e else v for v, e in zip(vals, errs)] if old_policy or n + err > nq else vals
    return [0.0 if v is None else v for v in vals] if not old_policy else vals


hist_raw = {}
for line in open(hist):
    if line.strip():
        r = json.loads(line)
        if r["ts"] in table_runs:
            hist_raw[(r["bench"], r["ts"], r["engine"])] = r
hist_adj = {(r["bench"], r["ts"], r["engine"]): r for r in load(hist) if r["ts"] in table_runs}

runs_by_bench = {}
used_ts = collections.defaultdict(set)
check = collections.Counter()
mismatch = []
for bench, (folder, report, m) in BENCHES.items():
    runs = []
    for d in sorted(glob.glob(os.path.join(site, folder, "*"))):
        name = os.path.basename(d)
        ts = name[:13] + ":" + name[13:15] + "Z"
        if ts not in table_runs or not os.path.exists(os.path.join(d, report)):
            continue
        rep = json.load(open(os.path.join(d, report)))
        pqs = {e: json.load(open(os.path.join(d, v["per_query_path"])))["per_query"] for e, v in rep["engines"].items()
               if os.path.isfile(os.path.join(d, v.get("per_query_path", "")))}
        if "ultimate" not in pqs or any(e not in pqs for e in KEEP):
            check[f"{bench}: run skipped, per-query files missing"] += 1
            continue
        gold = {}
        if bench == "finance":
            for line in open(os.path.join(d, "gold.jsonl")):
                if line.strip():
                    g = json.loads(line)
                    gold[g["query_text"]] = g
        ult_hits = collections.defaultdict(bool)
        engines = [e for e in pqs if e != "ultimate"] + ["ultimate"] if bench in ("finance", "legal") else KEEP + ["ultimate"]
        vals = {}
        for e in engines:
            v, errs = raw_values(bench, e, pqs[e], rep["engines"][e], gold, ult_hits)
            if bench in ("finance", "legal") and e != "ultimate":
                for q, x, er in zip(pqs[e], v, errs):
                    ult_hits[q["query"]] |= bool(x) and not er
            if e not in KEEP and e != "ultimate":
                continue
            h = hist_raw.get((bench, ts, e))
            n = sum(x is not None for x in v)
            mean = sum(x for x in v if x is not None) / n if n else None
            ok_raw = h is not None and n == h["num_scored"] and sum(errs) == (h.get("search_errors") or 0) and abs((mean or 0) - (h.get(m) or 0)) < 1e-9
            v2 = apply_policy(ts, e, v, errs)
            a = hist_adj.get((bench, ts, e))
            n2 = sum(x is not None for x in v2)
            mean2 = sum(x for x in v2 if x is not None) / n2 if n2 else None
            ok_adj = a is not None and n2 == a["num_scored"] and abs((mean2 or 0) - (a.get(m) or 0)) < 1e-9
            check[f"{bench}: raw row reproduced {ok_raw}"] += 1
            check[f"{bench}: policy-adjusted row reproduced {ok_adj}"] += 1
            if not (ok_raw and ok_adj):
                mismatch.append((bench, ts, e, n, mean, h and h["num_scored"], h and h.get(m), n2, mean2, a and a["num_scored"], a and a.get(m)))
            vals[e] = v2
        nq = len(pqs["ultimate"])
        assert all(len(vals[e]) == nq and all(pqs[e][i]["query"] == pqs["ultimate"][i]["query"] for i in range(nq)) for e in KEEP)
        acct = [any(pqs[e][i].get("search_error") is not None for e in ACCOUNT) for i in range(nq)]
        agg = {}
        for e in KEEP + ["ultimate"]:
            bs = [x for x in vals[e] if x is not None]
            ms = [x for x, f in zip(vals[e], acct) if x is not None and not f]
            agg[e] = (sum(bs), len(bs), sum(ms), len(ms))
        runs.append({"ts": ts, "agg": agg, "queries": nq, "matched": nq - sum(acct)})
        used_ts[bench].add(ts)
    runs_by_bench[bench] = runs
for k, v in sorted(check.items()):
    print(k, v)
for x in mismatch[:20]:
    print("  row mismatch", x)


def shares(runs_sel, matched):
    out = collections.defaultdict(dict)
    for bench, runs in runs_sel.items():
        tot = collections.defaultdict(lambda: [0.0, 0])
        for r in runs:
            for e, (bs, bn, ms, mn) in r["agg"].items():
                tot[e][0] += ms if matched else bs
                tot[e][1] += mn if matched else bn
        if not tot["ultimate"][1] or not tot["ultimate"][0]:
            continue
        u = tot["ultimate"][0] / tot["ultimate"][1]
        for e in KEEP:
            if tot[e][1]:
                out[e][bench] = tot[e][0] / tot[e][1] / u
    return out


def overall(sh):
    return {e: sum(b.values()) / len(b) for e, b in sh.items() if len(b) == len(runs_by_bench)}


base = overall(shares(runs_by_bench, False))
matched = overall(shares(runs_by_bench, True))
table1 = pairs_ref["base"]
sub_rows = [r for r in hist_adj.values() if r["ts"] in used_ts[r["bench"]]]
sh_sub, _ = c_shares(sub_rows, KEEP)
table1_sub = {e: c_overall(sh_sub, e) for e in KEEP}
dev = {e: 100 * (base[e] - table1[e]) for e in KEEP}
dev_sub = {e: 100 * (base[e] - table1_sub[e]) for e in KEEP}
print("runs used", {b: len(r) for b, r in runs_by_bench.items()}, "of", {b: len({t for (bb, t, _) in hist_raw if bb == b}) for b in BENCHES})
print("max |per-query base - Table 1| %.3f points (%s); same runs: %.6f" % (max(abs(x) for x in dev.values()), max(dev, key=lambda e: abs(dev[e])), max(abs(x) for x in dev_sub.values())))

order_t1 = pairs_ref["order"]
order_b = sorted(base, key=lambda e: -base[e])
order_m = sorted(matched, key=lambda e: -matched[e])
N = 1000
samp_m = collections.defaultdict(list)
samp_d = collections.defaultdict(list)
for _ in range(N):
    sel = {b: [runs[rng.randrange(len(runs))] for _ in runs] for b, runs in runs_by_bench.items()}
    m1 = overall(shares(sel, True))
    b1 = overall(shares(sel, False))
    for e in order_m:
        samp_m[e].append(m1.get(e, float("nan")))
        samp_d[e].append(m1.get(e, float("nan")) - b1.get(e, float("nan")))


def ci(xs):
    v = sorted(x for x in xs if x == x)
    return v[int(.025 * len(v))], v[int(.975 * len(v))]


Z = 3.683
pairs = {}
sep_pt = sep_bf = 0
unsep = []
for i, a in enumerate(order_m):
    for b in order_m[i + 1:]:
        d = [x - y for x, y in zip(samp_m[a], samp_m[b]) if x == x and y == y]
        lo, hi = ci(d)
        mu = sum(d) / len(d)
        sd = (sum((x - mu) ** 2 for x in d) / (len(d) - 1)) ** 0.5
        diff = matched[a] - matched[b]
        pt = lo > 0
        bf = diff - Z * sd > 0
        sep_pt += pt
        sep_bf += bf
        if not pt:
            unsep.append((a, b, round(100 * diff, 1)))
        pairs[f"{a}|{b}"] = {"diff": diff, "lo": lo, "hi": hi, "sep": pt, "sep_bonferroni": bf}
adj_sep = sum(pairs[f"{a}|{b}"]["sep"] for a, b in zip(order_m, order_m[1:]))
fully = [e for e in order_m if all(pairs.get(f"{e}|{f}", pairs.get(f"{f}|{e}"))["sep_bonferroni"] for f in order_m if f != e)]


def tau_b(a, b):
    c = d = 0
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            x = (a.index(a[i]) - a.index(a[j])) * (b.index(a[i]) - b.index(a[j]))
            c += x > 0
            d += x < 0
    return (c - d) / (c + d)


print("tau_b matched vs per-query base %.3f; vs Table 1 order %.3f; base vs Table 1 order %.3f" % (tau_b(order_b, order_m), tau_b(order_t1, order_m), tau_b(order_t1, order_b)))
for e in order_t1:
    lo, hi = ci(samp_d[e])
    print(f"  {e:17s} T1 {100*table1[e]:5.2f} base {100*base[e]:5.2f} (rank {order_b.index(e)+1:2d}) matched {100*matched[e]:5.2f} (rank {order_m.index(e)+1:2d}) diff {100*(matched[e]-base[e]):+.1f} [{100*lo:+.1f},{100*hi:+.1f}]")
print("matched support: adjacent separated", adj_sep, "of", len(order_m) - 1, "; all pairs separated", sep_pt, "of", len(pairs), "; Bonferroni", sep_bf)
print("fully separated (Bonferroni):", fully)
print("unseparated:", unsep)
json.dump({"scorer": "paper (site: requested host only; finance 0.1% band, table readings, no money backstop; rare duplicate penalty on every query; Table 1 failure policy)",
           "runs": {b: len(r) for b, r in runs_by_bench.items()}, "queries": {b: sum(x["queries"] for x in r) for b, r in runs_by_bench.items()},
           "matched_queries": {b: sum(x["matched"] for x in r) for b, r in runs_by_bench.items()}, "row_check": dict(check), "row_mismatches": mismatch,
           "table1": table1, "table1_same_runs": table1_sub, "base_minus_table1_points": dev,
           "base": base, "matched": matched, "ci_diff": {e: ci(samp_d[e]) for e in order_m}, "tau_b": tau_b(order_b, order_m), "tau_b_table1_order": tau_b(order_t1, order_m),
           "adjacent_separated": adj_sep, "pairs_separated": sep_pt, "pairs_separated_bonferroni": sep_bf, "fully_separated_bonferroni": fully,
           "pairs": pairs, "order_matched": order_m, "order_base": order_b}, open(out_json, "w"), indent=1)
