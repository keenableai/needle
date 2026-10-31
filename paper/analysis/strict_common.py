import collections
import glob
import json
import os
import sys

site, history, out_json = sys.argv[1], sys.argv[2], sys.argv[3]
LO, HI = "2026-10-17", "2026-10-30"
KEEP = "keenable exa google bing brave brave-llmcontext parallel perplexity tavily linkup tinyfish octen ceramic you firecrawl kagi jina context deepseek claude-search chatgpt-search".split()
ACCOUNT = {"perplexity", "exa", "kagi", "parallel", "claude-search"}
BENCHES = {
    "scholar": ("hfscholar", "scholar.json", "hit"),
    "news": ("hfnews", "ndcg.json", "ndcg"),
    "finance": ("hf", "recall.json", "hit"),
    "agentic_rare": ("hfrare", "agentic_rare.json", "ndcg"),
    "legal": ("hflegal", "legal.json", "hit"),
}

excluded = collections.defaultdict(int)
total = collections.defaultdict(int)
for line in open(history):
    if not line.strip():
        continue
    r = json.loads(line)
    if r["bench"] not in BENCHES or not (LO <= r["ts"][:10] < HI) or r["engine"] not in KEEP:
        continue
    total[(r["engine"], r["bench"])] += r.get("num_queries") or 0
    if r["engine"] in ACCOUNT:
        excluded[(r["engine"], r["bench"])] += r.get("search_errors") or 0


def value(pq, kind):
    if kind == "ndcg":
        return float(pq.get("ndcg") or 0.0)
    return 1.0 if pq.get("hit_rank") is not None else 0.0


def tau_b(a, b):
    n = len(a)
    c = d = ta = tb = 0
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


base_share = collections.defaultdict(dict)
strict_share = collections.defaultdict(dict)
retained = {}
for bench, (folder, report, kind) in BENCHES.items():
    base_sum = collections.defaultdict(float)
    base_n = collections.defaultdict(int)
    ult_sum = 0.0
    ult_n = 0
    s_sum = collections.defaultdict(float)
    s_n = 0
    s_ult = 0.0
    n_runs = 0
    n_q = 0
    for d in sorted(glob.glob(os.path.join(site, folder, "*"))):
        name = os.path.basename(d)
        if not (LO <= name[:10] < HI) or not os.path.exists(os.path.join(d, report)):
            continue
        rep = json.load(open(os.path.join(d, report)))
        pqs = {}
        for e in KEEP + ["ultimate"]:
            if e in rep["engines"]:
                p = os.path.join(d, rep["engines"][e].get("per_query_path", ""))
                if os.path.isfile(p):
                    pqs[e] = json.load(open(p))["per_query"]
                elif "per_query" in rep["engines"][e]:
                    pqs[e] = rep["engines"][e]["per_query"]
        present = [e for e in KEEP if e in pqs]
        if len(present) < 20 or "ultimate" not in pqs:
            continue
        n_runs += 1
        nq = len(pqs["ultimate"])
        n_q += nq
        for qi in range(nq):
            u = value(pqs["ultimate"][qi], kind)
            ult_sum += u
            ult_n += 1
            answered = True
            for e in present:
                pq = pqs[e][qi]
                failed = pq.get("search_error") is not None
                if failed and e in ACCOUNT:
                    answered = False
                    continue
                if failed:
                    answered = False
                base_sum[e] += 0.0 if failed else value(pq, kind)
                base_n[e] += 1
            if answered:
                s_n += 1
                s_ult += u
                for e in present:
                    s_sum[e] += value(pqs[e][qi], kind)
    if not n_runs:
        continue
    retained[bench] = {"runs": n_runs, "queries": n_q, "strict_queries": s_n}
    u_mean = ult_sum / ult_n
    su_mean = s_ult / s_n if s_n else None
    for e in KEEP:
        if base_n.get(e):
            base_share[e][bench] = base_sum[e] / base_n[e] / u_mean
        if s_n and e in s_sum:
            strict_share[e][bench] = s_sum[e] / s_n / su_mean

names = [e for e in KEEP if len(base_share.get(e, {})) == len(retained) and len(strict_share.get(e, {})) == len(retained)]
base_ov = {e: sum(base_share[e].values()) / len(retained) for e in names}
strict_ov = {e: sum(strict_share[e].values()) / len(retained) for e in names}
order_b = sorted(names, key=lambda e: -base_ov[e])
order_s = sorted(names, key=lambda e: -strict_ov[e])
tau = tau_b([base_ov[e] for e in names], [strict_ov[e] for e in names])
moves = {e: (round(base_ov[e] * 100, 1), round(strict_ov[e] * 100, 1), order_b.index(e) + 1, order_s.index(e) + 1) for e in names}
json.dump({"retained": retained, "excluded": {f"{e}|{b}": v for (e, b), v in excluded.items()}, "total": {f"{e}|{b}": v for (e, b), v in total.items()}, "base": base_ov, "strict": strict_ov, "tau_b": tau, "moves": moves}, open(out_json, "w"), indent=1)

print("retained", retained)
print("engines compared", len(names), "tau_b base vs strict %.3f" % tau)
for e in order_b:
    b, s, rb, rs = moves[e]
    flag = " *" if abs(s - b) >= 1.0 or rb != rs else ""
    print(f"  {e:17s} base {b:5.1f} (rank {rb:2d})  strict {s:5.1f} (rank {rs:2d}){flag}")
print("account-side excluded query-runs by engine|bench (excluded/total):")
for e in sorted(ACCOUNT):
    print("  ", e, {b: f"{excluded[(e, b)]}/{total[(e, b)]}" for b in BENCHES})
