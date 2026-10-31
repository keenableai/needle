import json, sys, collections, random, statistics
from datetime import datetime, timedelta

hist, indep = sys.argv[1], sys.argv[2]
rows = [json.loads(l) for l in open(hist) if l.strip()]
FMT = "%Y-%m-%dT%H:%MZ"
BENCHES = [("scholar", "recall"), ("news", "ndcg"), ("finance", "recall"), ("agentic_rare", "ndcg"), ("legal", "recall")]
ULT = "ultimate"

def window(rows, days, end=None):
    end = end or max(datetime.strptime(r["ts"], FMT) for r in rows)
    cut = end - timedelta(days=days)
    return [r for r in rows if cut < datetime.strptime(r["ts"], FMT) <= end], end

def wmean(rs, metric):
    num = sum(r[metric] * r["num_scored"] for r in rs if r.get(metric) is not None and r["num_scored"])
    den = sum(r["num_scored"] for r in rs if r.get(metric) is not None and r["num_scored"])
    return num / den if den else None

def shares(rs, engines):
    out = {}
    ult = {}
    for b, m in BENCHES:
        br = [r for r in rs if r["bench"] == b]
        ult[b] = wmean([r for r in br if r["engine"] == ULT], m)
        for e in engines:
            v = wmean([r for r in br if r["engine"] == e], m)
            out.setdefault(e, {})[b] = (v, v / ult[b] if v is not None and ult[b] else None)
    return out, ult

def bootstrap(rs, engines, n=2000, seed=1926):
    rnd = random.Random(seed)
    runs_by_bench = {}
    for b, m in BENCHES:
        byts = collections.defaultdict(list)
        for r in rs:
            if r["bench"] == b and r.get(m) is not None and r["num_scored"]:
                byts[r["ts"]].append((r["engine"], r[m], r["num_scored"]))
        runs_by_bench[b] = list(byts.values())
    overall = collections.defaultdict(list)
    bench_s = {b: collections.defaultdict(list) for b, _ in BENCHES}
    for _ in range(n):
        acc = collections.defaultdict(float); accn = collections.Counter()
        for b, _m in BENCHES:
            runs = runs_by_bench[b]
            if not runs: continue
            sums = collections.defaultdict(float); wts = collections.defaultdict(float)
            for _k in range(len(runs)):
                for e, v, w in runs[rnd.randrange(len(runs))]:
                    sums[e] += v * w; wts[e] += w
            if not wts[ULT]: continue
            u = sums[ULT] / wts[ULT]
            if not u: continue
            for e in engines:
                if wts[e]:
                    s = sums[e] / wts[e] / u
                    bench_s[b][e].append(s); acc[e] += s; accn[e] += 1
        for e in engines:
            if accn[e]: overall[e].append(acc[e] / accn[e])
    def pct(xs, p):
        xs = sorted(xs); return xs[min(len(xs) - 1, int(p * len(xs)))]
    return {e: (pct(v, .025), pct(v, .975)) for e, v in overall.items()}, {b: {e: (pct(v, .025), pct(v, .975)) for e, v in d.items()} for b, d in bench_s.items()}

days = int(sys.argv[3]) if len(sys.argv) > 3 else 30
live = [r for r in rows if r["bench"] in dict(BENCHES)]
w, end = window(live, days)
print(f"window {days}d ending {end}")
engines = sorted({r["engine"] for r in w} - {ULT})
sh, ult = shares(w, engines)
ci, bci = bootstrap(w, engines)
print("ultimate absolute:", {b: round(v, 3) for b, v in ult.items()})
table = []
for e in engines:
    vals = [sh[e][b][1] for b, _ in BENCHES]
    have = [v for v in vals if v is not None]
    if len(have) < len(BENCHES): continue
    table.append((sum(have) / len(have), e, vals))
table.sort(reverse=True)
print("engine | overall share [CI] | " + " | ".join(b for b, _ in BENCHES) + "  (abs metric in parens)")
for o, e, vals in table:
    lo, hi = ci[e]
    cells = " | ".join(f"{sh[e][b][1]*100:.1f} ({sh[e][b][0]:.3f})" for b, _ in BENCHES)
    print(f"{e:18s} {o*100:5.1f} [{lo*100:.1f},{hi*100:.1f}] | {cells}")
print("per-bench CI widths (pp) for top engines:")
for o, e, vals in table[:6]:
    print(e, {b: f"{(bci[b][e][1]-bci[b][e][0])*100:.1f}" for b, _ in BENCHES})

print("\n=== runs/queries in window ===")
for b, m in BENCHES:
    br = [r for r in w if r["bench"] == b and r["engine"] == ULT]
    print(b, "runs", len(br), "queries", sum(r["num_queries"] for r in br))
print("\n=== all-time totals (live benches) ===")
for b, m in BENCHES:
    br = [r for r in live if r["bench"] == b and r["engine"] == ULT]
    print(b, "runs", len(br), "queries", sum(r["num_queries"] for r in br), "first", min(r["ts"] for r in br))

print("\n=== bucket breakdowns (window, query-weighted) ===")
def wkey(rs, key, nkey):
    num = sum(r[key] * r[nkey] for r in rs if r.get(key) is not None and r.get(nkey))
    den = sum(r[nkey] for r in rs if r.get(key) is not None and r.get(nkey))
    return num / den if den else None
sch = [r for r in w if r["bench"] == "scholar"]
keys = sorted({k for r in sch for k in r if k.endswith("_recall")})
print("scholar keys", keys)
for o, e, _ in table + [(0, ULT, None)]:
    rs = [r for r in sch if r["engine"] == e]
    print(f"{e:18s}", {k.replace('_recall',''): round(wkey(rs, k, k.replace('_recall', '_n')) or 0, 3) for k in keys}, "mrr", round(wmean(rs, "mrr") or 0, 3))
leg = [r for r in w if r["bench"] == "legal"]
print("legal")
for o, e, _ in table + [(0, ULT, None)]:
    rs = [r for r in leg if r["engine"] == e]
    print(f"{e:18s}", "caselaw", round(wkey(rs, "caselaw_recall", "caselaw_n") or 0, 3), "code", round(wkey(rs, "code_recall", "code_n") or 0, 3), "plain", round(wmean(rs, "plain_recall") or 0, 3), "op", round(wmean(rs, "op_recall") or 0, 3))
fin = [r for r in w if r["bench"] == "finance"]
print("finance")
for o, e, _ in table + [(0, ULT, None)]:
    rs = [r for r in fin if r["engine"] == e]
    print(f"{e:18s}", "recall", round(wmean(rs, "recall") or 0, 3), "filings", round(wkey(rs, "filings_recall", "filings_n") or 0, 3), "filingdoc", round(wkey(rs, "filingdoc_recall", "filingdoc_n") or 0, 3), "plain", round(wmean(rs, "plain_recall") or 0, 3), "op", round(wmean(rs, "op_recall") or 0, 3), "mrr", round(wmean(rs, "mrr") or 0, 3))

print("\n=== latency p50 (median of run p50s, window, news bench) ===")
for o, e, _ in table:
    p = [r["p50_ms"] for r in w if r["engine"] == e and r["bench"] == "news" and r.get("p50_ms")]
    print(f"{e:18s}", round(statistics.median(p)) if p else None, "n", len(p))

print("\n=== weekly stability: overall share per ISO week (last 8 weeks) ===")
weeks = collections.defaultdict(list)
for r in live:
    d = datetime.strptime(r["ts"], FMT)
    weeks[d.strftime("%G-W%V")].append(r)
wk = sorted(weeks)[-9:-1]
core = [e for _, e, _ in table]
ranks = {}
for k in wk:
    s, _u = shares(weeks[k], core)
    ov = {}
    for e in core:
        vals = [s[e][b][1] for b, _ in BENCHES if s[e][b][1] is not None]
        if len(vals) == len(BENCHES): ov[e] = sum(vals) / len(vals)
    ranks[k] = ov
    print(k, " ".join(f"{e}:{v*100:.0f}" for e, v in sorted(ov.items(), key=lambda x: -x[1])))
def kendall(a, b):
    es = [e for e in a if e in b]
    c = d = 0
    for i in range(len(es)):
        for j in range(i + 1, len(es)):
            x = (a[es[i]] - a[es[j]]) * (b[es[i]] - b[es[j]])
            c += x > 0; d += x < 0
    return (c - d) / (c + d) if c + d else None
print("kendall tau consecutive weeks:", [round(kendall(ranks[wk[i]], ranks[wk[i+1]]), 2) for i in range(len(wk) - 1)])

print("\n=== independence ===")
ind = json.load(open(indep))
print("keys", list(ind), {k: list(v) for k, v in ind.items()})
for scope in ind:
    ov = ind[scope].get("overlap", [])
    fam = {"keenable-realtime": "keenable", "exa-instant": "exa", "exa-lite": "exa", "parallel-turbo": "parallel", "perplexity-fast": "perplexity", "brave-llmcontext": "brave"}
    base = [x for x in ov if x["a"] not in fam and x["b"] not in fam]
    js = sorted(((x["shared_urls"] / x["union_urls"], x["a"], x["b"], x["num_queries"]) for x in base if x["union_urls"]), reverse=True)
    print(scope, "pairs", len(base), "jaccard max", [(round(j, 3), a, b) for j, a, b, n in js[:6]], "median", round(statistics.median([j for j, *_ in js]), 3), "min", [(round(j, 3), a, b) for j, a, b, n in js[-3:]])
    un = ind[scope].get("uniqueness", [])
    if un:
        print(" uniqueness sample", un[:3])
