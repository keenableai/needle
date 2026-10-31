import collections
import glob
import json
import os
import random
import sys

site, pairs_json, out_json = sys.argv[1], sys.argv[2], sys.argv[3]
KEEP = "keenable exa google bing brave brave-llmcontext parallel perplexity tavily linkup tinyfish octen ceramic you firecrawl kagi jina context deepseek claude-search chatgpt-search".split()
ACCOUNT = {"perplexity", "exa", "kagi", "parallel", "claude-search"}
BENCHES = {"scholar": ("hfscholar", "scholar.json", "hit"), "news": ("hfnews", "ndcg.json", "ndcg"), "finance": ("hf", "recall.json", "hit"),
           "agentic_rare": ("hfrare", "agentic_rare.json", "ndcg"), "legal": ("hflegal", "legal.json", "hit")}
table_runs = {ts.replace(":", "") for ts in json.load(open(pairs_json))["runs"]}
rng = random.Random(17)


def value(pq, kind):
    if kind == "ndcg":
        return float(pq.get("ndcg") or 0.0)
    return 1.0 if pq.get("hit_rank") is not None else 0.0


def paper_key(d):
    out = {}
    p = os.path.join(d, "scholar.jsonl")
    if os.path.exists(p):
        for line in open(p):
            if line.strip():
                g = json.loads(line)
                o = g["query_origin"]
                o = json.loads(o) if isinstance(o, str) else o
                out[g["query_text"]] = o.get("provenance", {}).get("url") or o.get("provenance", {}).get("title") or g["query_text"]
    return out


clusters_by_bench = {}
for bench, (folder, report, kind) in BENCHES.items():
    clusters = collections.defaultdict(list)
    for d in sorted(glob.glob(os.path.join(site, folder, "*"))):
        name = os.path.basename(d)
        if name not in table_runs or not os.path.exists(os.path.join(d, report)):
            continue
        rep = json.load(open(os.path.join(d, report)))
        pqs = {}
        for e in KEEP + ["ultimate"]:
            if e in rep["engines"]:
                p = os.path.join(d, rep["engines"][e].get("per_query_path", ""))
                if os.path.isfile(p):
                    pqs[e] = json.load(open(p))["per_query"]
        if "ultimate" not in pqs or len([e for e in KEEP if e in pqs]) < 21:
            continue
        pk = paper_key(d) if bench == "scholar" else {}
        for qi in range(len(pqs["ultimate"])):
            text = pqs["ultimate"][qi]["query"]
            vals = {}
            for e in KEEP:
                pq = pqs[e][qi]
                failed = pq.get("search_error") is not None
                vals[e] = None if (failed and e in ACCOUNT) else (0.0 if failed else value(pq, kind))
            clusters[pk.get(text, text)].append({"u": value(pqs["ultimate"][qi], kind), "vals": vals})
    clusters_by_bench[bench] = list(clusters.values())
    print(bench, "clusters", len(clusters), "query-runs", sum(len(v) for v in clusters.values()), flush=True)


def shares(sel):
    out = collections.defaultdict(dict)
    for bench, cl in sel.items():
        use = [q for c in cl for q in c]
        u = sum(q["u"] for q in use) / len(use)
        if not u:
            continue
        for e in KEEP:
            vs = [q["vals"][e] for q in use if q["vals"].get(e) is not None]
            if vs:
                out[e][bench] = sum(vs) / len(vs) / u
    return out


def overall(sh):
    return {e: sum(b.values()) / len(b) for e, b in sh.items() if len(b) == len(clusters_by_bench)}


base = overall(shares(clusters_by_bench))
order = sorted(base, key=lambda e: -base[e])
N = 1000
samp = collections.defaultdict(list)
for _ in range(N):
    sel = {b: [cl[rng.randrange(len(cl))] for _ in cl] for b, cl in clusters_by_bench.items()}
    o = overall(shares(sel))
    for e in order:
        samp[e].append(o.get(e, float("nan")))


def ci(xs):
    v = sorted(x for x in xs if x == x)
    return v[int(.025 * len(v))], v[int(.975 * len(v))]


Z = 3.683
pairs = {}
sep_pt = sep_bf = 0
for i, a in enumerate(order):
    for b in order[i + 1:]:
        d = [x - y for x, y in zip(samp[a], samp[b]) if x == x and y == y]
        lo, hi = ci(d)
        mu = sum(d) / len(d)
        sd = (sum((x - mu) ** 2 for x in d) / (len(d) - 1)) ** 0.5
        diff = base[a] - base[b]
        pt, bf = lo > 0, diff - Z * sd > 0
        sep_pt += pt
        sep_bf += bf
        pairs[f"{a}|{b}"] = {"diff": diff, "lo": lo, "hi": hi, "sep": pt, "sep_bonferroni": bf}
adj = sum(pairs[f"{a}|{b}"]["sep"] for a, b in zip(order, order[1:]))
fully = [e for e in order if all(pairs.get(f"{e}|{f}", pairs.get(f"{f}|{e}"))["sep_bonferroni"] for f in order if f != e)]
lead = pairs.get("keenable|exa") or pairs.get("exa|keenable")
print(f"cluster bootstrap: pointwise separated {sep_pt}/210, Bonferroni {sep_bf}/210, adjacent {adj}/20; fully separated {fully}")
print("keenable-exa diff %.3f ci [%.3f, %.3f]" % (lead["diff"], lead["lo"], lead["hi"]))
json.dump({"order": order, "overall": base, "pairs": pairs, "pointwise": sep_pt, "bonferroni": sep_bf, "adjacent": adj, "fully": fully,
           "clusters": {b: len(cl) for b, cl in clusters_by_bench.items()}}, open(out_json, "w"), indent=1)
