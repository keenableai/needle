import collections
import functools
import json
import os
import random
import re
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


REPORT_FILES = {"scholar": "scholar.json", "news": "ndcg.json", "finance": "recall.json", "agentic_rare": "agentic_rare.json", "legal": "legal.json"}
ACCOUNT_STATUSES = frozenset({401, 402, 403, 432, 433})
MESSAGE_STATUSES = frozenset({None, 400, 429})
ACCOUNT_MESSAGE = re.compile(
    r"credit[ _]balance|not enough credits|insufficient[ _]credits|usage limit"
    r"|\bquota\b|insufficient_quota|billing|api[ _-]?key",
    re.IGNORECASE,
)
HTTP_STATUS = re.compile(r"(\d{3}):")


def account_side(error):
    kind, message = error.get("error_type"), error.get("error_message") or ""
    if kind not in ("http_error", "api_error"):
        return False
    status = HTTP_STATUS.match(message) if kind == "http_error" else None
    code = int(status.group(1)) if status else None
    return code in ACCOUNT_STATUSES or (code in MESSAGE_STATUSES and ACCOUNT_MESSAGE.search(message) is not None)


def account_errors(r):
    if "account_errors" in r:
        return r["account_errors"]
    return (r.get("search_errors") or 0) if r["engine"] in ACCOUNT_SIDE_FAILURES else 0


def rescore(value, n, pairs):
    ok = sum(q["search_error"] is None and scored for q, scored in pairs)
    failed = [(q["search_error"], scored) for q, scored in pairs if q["search_error"] is not None]
    new_n = ok + sum(scored and not account_side(e) for e, scored in failed)
    assert n in (ok, ok + sum(scored for _, scored in failed), ok + len(failed)), (n, ok, len(failed))
    if new_n == n:
        return value, n
    return ((value or 0) * n / new_n if new_n else None), new_n


def split(r, per_query, ceiling):
    errors = [q["search_error"] for q in per_query if q["search_error"] is not None]
    acc = sum(map(account_side, errors))
    r = {**r, "account_errors": acc, "service_errors": len(errors) - acc}
    if not errors:
        return r
    m = dict(BENCHES)[r["bench"]]
    pairs = list(zip(per_query, ceiling, strict=True))
    n = r["num_scored"]
    r[m], r["num_scored"] = rescore(r[m], n, pairs)
    if r.get("mrr") is not None and r["num_scored"] != n:
        r["mrr"] = r["mrr"] * n / r["num_scored"] if r["num_scored"] else None
    for k in [k for k in r if k.endswith("_n") and r[k] and f"{k[:-2]}_recall" in r]:
        b = k[:-2]
        r[f"{b}_recall"], r[k] = rescore(r[f"{b}_recall"], r[k], [(q, s) for q, s in pairs if q.get("bucket") == b])
    return r


@functools.lru_cache(maxsize=32)
def report(run, bench):
    return json.load(open(os.path.join(run, REPORT_FILES[bench])))


def per_query(run, bench, engine):
    p = os.path.join(run, (report(run, bench)["engines"].get(engine) or {}).get("per_query_path", ""))
    return json.load(open(p))["per_query"] if os.path.isfile(p) else None


def with_ceiling(run, bench, n):
    if dict(BENCHES)[bench] != "ndcg":
        return [True] * n
    return [q["ndcg"] is not None for q in per_query(run, bench, ULT)]


def scored_failures(run, bench, engine):
    pq = per_query(run, bench, engine)
    sides = [account_side(q["search_error"]) for q, c in zip(pq, with_ceiling(run, bench, len(pq)), strict=True)
             if c and q["search_error"] is not None]
    return sum(sides), len(sides) - sum(sides)


def run_dirs(site):
    runs = {}
    for folder in ["hf", "hfnews", "hfrare", "hfscholar", "hflegal"] + [f"prospective/{b}" for b in REPORT_FILES]:
        for name in sorted(os.listdir(os.path.join(site, folder))):
            for bench, rep in REPORT_FILES.items():
                if os.path.isfile(os.path.join(site, folder, name, rep)):
                    runs[(bench, name[:13] + ":" + name[13:15] + "Z")] = os.path.join(site, folder, name)
    return runs


def classify(rows, runs):
    out, unsplit = [], []
    for r in rows:
        if not r.get("search_errors"):
            out.append({**r, "account_errors": 0, "service_errors": 0})
            continue
        run = runs.get((r["bench"], r["ts"]))
        pq = per_query(run, r["bench"], r["engine"]) if run else None
        if pq is None:
            out.append(r)
            unsplit.append(r)
            continue
        out.append(split(r, pq, with_ceiling(run, r["bench"], len(pq))))
    return out, unsplit


def load(path):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    rows = [r for r in rows if r["bench"] in dict(BENCHES)]
    for r in rows:
        m = dict(BENCHES)[r["bench"]]
        err, nq = r.get("search_errors") or 0, r.get("num_queries") or 0
        if "account_errors" in r or not err or not nq or r.get(m) is None:
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
