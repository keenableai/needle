import collections
import json
import math
import random
import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit

FMT = "%Y-%m-%dT%H:%MZ"
BENCHES = [("scholar", "recall"), ("news", "ndcg"), ("finance", "recall"), ("agentic_rare", "ndcg"), ("legal", "recall")]
ULT = "ultimate"
FAMILIES = {
    "keenable-realtime": "keenable", "exa-instant": "exa", "exa-lite": "exa",
    "parallel-turbo": "parallel", "perplexity-fast": "perplexity", "brave-llmcontext": "brave",
}
KEEP = "keenable exa google bing brave brave-llmcontext parallel perplexity tavily linkup tinyfish octen ceramic you firecrawl kagi jina context deepseek claude-search chatgpt-search".split()
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
SITE_RE = re.compile(r"site:(\S+)")


def account_errors(r):
    return r.get("account_errors") or 0


def load(path):
    rows = [json.loads(line) for line in open(path) if line.strip()]
    return [r for r in rows if r["bench"] in dict(BENCHES)]


def window(rows, days, end=None):
    end = end or max(datetime.strptime(r["ts"], FMT) for r in rows)
    cut = end - timedelta(days=days)
    return [r for r in rows if cut < datetime.strptime(r["ts"], FMT) <= end], end


def kept_engines(engines):
    return [e for e in sorted(set(engines) - {ULT}) if e not in FAMILIES or e == "brave-llmcontext"]


def table_window(rows, days=30):
    w, _ = window(rows, days)
    engines = sorted({r["engine"] for r in w} - {ULT})
    keep = kept_engines(engines)
    full_ts = set()
    for b, m in BENCHES:
        by_ts = collections.defaultdict(set)
        for r in w:
            if r["bench"] == b and ((r.get(m) is not None and r["num_scored"]) or account_errors(r)):
                by_ts[r["ts"]].add(r["engine"])
        full_ts |= {ts for ts, es in by_ts.items() if all(e in es for e in keep)}
    return [r for r in w if r["ts"] in full_ts], engines, keep


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

    return {e: (pct(v, .025), pct(v, .975)) for e, v in samples.items()}


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


def ci(xs):
    v = [x for x in xs if x == x]
    return pct(v, .025), pct(v, .975)


def wilson(k, n, z=1.96):
    if not n:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def bucket_recall(rs, engine, bucket):
    pairs = [(r[f"{bucket}_recall"], r[f"{bucket}_n"]) for r in rs
             if r["engine"] == engine and r.get(f"{bucket}_recall") is not None and r.get(f"{bucket}_n")]
    den = sum(n for _, n in pairs)
    return sum(v * n for v, n in pairs) / den if den else None


def tau_b(x, y):
    c = d = tx = ty = 0
    for i in range(len(x)):
        for j in range(i + 1, len(x)):
            dx, dy = x[i] - x[j], y[i] - y[j]
            if dx == 0 and dy == 0:
                continue
            if dx == 0:
                tx += 1
            elif dy == 0:
                ty += 1
            elif dx * dy > 0:
                c += 1
            else:
                d += 1
    den = ((c + d + tx) * (c + d + ty)) ** 0.5
    return (c - d) / den if den else float("nan")


def order_tau(a, b):
    return tau_b(range(len(a)), [b.index(e) for e in a])


def host_ok(url, site):
    h = (urlsplit(url).hostname or "").lower()
    return h == site or h.endswith("." + site)
