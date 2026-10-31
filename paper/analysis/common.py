import collections
import json
import random
from datetime import datetime, timedelta

FMT = "%Y-%m-%dT%H:%MZ"
BENCHES = [("scholar", "recall"), ("news", "ndcg"), ("finance", "recall"), ("agentic_rare", "ndcg"), ("legal", "recall")]
ULT = "ultimate"
FAMILIES = {
    "keenable-realtime": "keenable", "exa-instant": "exa", "exa-lite": "exa",
    "parallel-turbo": "parallel", "perplexity-fast": "perplexity", "brave-llmcontext": "brave",
}
NAMES = {
    "keenable": "Keenable", "exa": "Exa", "brave-llmcontext": "Brave (LLM ctx)", "perplexity": "Perplexity",
    "parallel": "Parallel", "brave": "Brave", "you": "You.com", "linkup": "Linkup", "deepseek": "DeepSeek",
    "context": "Context", "kagi": "Kagi", "firecrawl": "Firecrawl", "chatgpt-search": "ChatGPT search",
    "google": "Google (Serper)", "octen": "Octen", "bing": "Bing (SearchAPI)", "claude-search": "Claude search",
    "jina": "Jina", "tavily": "Tavily", "tinyfish": "TinyFish", "ceramic": "Ceramic",
}
COLORS = {
    "keenable": "#0072B2", "exa": "#009E73", "perplexity": "#D55E00", "parallel": "#E69F00",
    "google": "#56B4E9", "chatgpt-search": "#000000", "claude-search": "#CC79A7", "brave-llmcontext": "#F0E442",
    "ultimate": "#898781",
}
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SURFACE = "#fcfcfb"
BLUES = ["#ffffff", "#e6f0fc", "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6"]


FAILURE_EXCLUDED_SINCE = datetime(2026, 10, 26, 22, 19)
ACCOUNT_SIDE_FAILURES = {"perplexity", "perplexity-fast", "exa", "exa-instant", "exa-lite", "kagi", "parallel", "parallel-turbo", "claude-search"}


def load(path):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    rows = [r for r in rows if r["bench"] in dict(BENCHES)]
    for r in rows:
        m = dict(BENCHES)[r["bench"]]
        err, nq = r.get("search_errors") or 0, r.get("num_queries") or 0
        if not err or not nq or r.get(m) is None:
            continue
        old_policy = datetime.strptime(r["ts"], FMT) < FAILURE_EXCLUDED_SINCE
        if r["engine"] in ACCOUNT_SIDE_FAILURES:
            if old_policy or r["num_scored"] + err > nq:
                good = r["num_scored"] - err
                r[m] = r[m] * r["num_scored"] / good if good > 0 else None
                r["num_scored"] = max(good, 0)
        elif not old_policy:
            r[m] = r[m] * r["num_scored"] / nq
            r["num_scored"] = nq
    return rows


def window(rows, days, end=None):
    end = end or max(datetime.strptime(r["ts"], FMT) for r in rows)
    cut = end - timedelta(days=days)
    return [r for r in rows if cut < datetime.strptime(r["ts"], FMT) <= end], end


def wmean(rs, metric):
    pairs = [(r[metric], r["num_scored"]) for r in rs if r.get(metric) is not None and r["num_scored"]]
    den = sum(n for _, n in pairs)
    return sum(v * n for v, n in pairs) / den if den else None


def shares(rs, engines):
    out, ult = {}, {}
    for b, m in BENCHES:
        br = [r for r in rs if r["bench"] == b]
        ult[b] = wmean([r for r in br if r["engine"] == ULT], m)
        for e in engines:
            v = wmean([r for r in br if r["engine"] == e], m)
            out.setdefault(e, {})[b] = (v, v / ult[b] if v is not None and ult[b] else None)
    return out, ult


def overall(sh, e):
    vals = [sh[e][b][1] for b, _ in BENCHES]
    return sum(vals) / len(vals) if all(v is not None for v in vals) else None


def bootstrap(rs, engines, n=2000, seed=1926):
    rnd = random.Random(seed)
    runs_by_bench = {}
    for b, m in BENCHES:
        byts = collections.defaultdict(list)
        for r in rs:
            if r["bench"] == b and r.get(m) is not None and r["num_scored"]:
                byts[r["ts"]].append((r["engine"], r[m], r["num_scored"]))
        runs_by_bench[b] = list(byts.values())
    samples = collections.defaultdict(list)
    for _ in range(n):
        acc = collections.defaultdict(float)
        accn = collections.Counter()
        for b, _m in BENCHES:
            runs = runs_by_bench[b]
            sums = collections.defaultdict(float)
            wts = collections.defaultdict(float)
            for _k in range(len(runs)):
                for e, v, w in runs[rnd.randrange(len(runs))]:
                    sums[e] += v * w
                    wts[e] += w
            if not wts[ULT] or not sums[ULT]:
                continue
            u = sums[ULT] / wts[ULT]
            for e in engines:
                if wts[e]:
                    acc[e] += sums[e] / wts[e] / u
                    accn[e] += 1
        for e in engines:
            if accn[e]:
                samples[e].append(acc[e] / accn[e])

    def pct(xs, p):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(p * len(xs)))]

    return {e: (pct(v, .025), pct(v, .975)) for e, v in samples.items()}


def bucket_recall(rs, engine, bucket):
    pairs = [(r[f"{bucket}_recall"], r[f"{bucket}_n"]) for r in rs
             if r["engine"] == engine and r.get(f"{bucket}_recall") is not None and r.get(f"{bucket}_n")]
    den = sum(n for _, n in pairs)
    return sum(v * n for v, n in pairs) / den if den else None


def weekly_shares(rows, engines, weeks):
    byweek = collections.defaultdict(list)
    for r in rows:
        byweek[datetime.strptime(r["ts"], FMT).strftime("%G-W%V")].append(r)
    keys = sorted(byweek)[-weeks - 1:-1]
    out = {}
    for k in keys:
        sh, _ = shares(byweek[k], engines)
        out[k] = {e: overall(sh, e) for e in engines}
    return out
