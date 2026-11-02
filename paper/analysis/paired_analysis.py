import collections
import json
import random
import sys
from urllib.parse import urlsplit

from common import host_ok, pct

from needle.shared.search.errors import account_side

out_json = sys.argv[1]
pairs = sys.argv[2:]
rng = random.Random(5)
VARIANTS = ("quoted", "site", "date")
BUCKET_ORDER = ("caselaw", "code", "filing")
REDIRECT_MIN = 0.01


def redirect(url):
    return urlsplit(url).path == "/goto" and host_ok(url, "google.com")


obs = collections.defaultdict(lambda: collections.defaultdict(dict))
counts = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
for i in range(0, len(pairs), 2):
    qfile, ofile = pairs[i], pairs[i + 1]
    meta = {}
    for line in open(qfile):
        if line.strip():
            g = json.loads(line)
            o = json.loads(g["query_origin"])
            meta[g["query_text"]] = (o["paired_target"], o["syntax"])
    rep = json.load(open(ofile))
    for eng, e in rep["engines"].items():
        if eng == "ultimate":
            continue
        for pq in e["per_query"]:
            target, syntax = meta[pq["query"]]
            bucket = target.split(":", 1)[0]
            c = counts[eng][bucket]
            c["requests"] += 1
            results = pq.get("results") or []
            c["results"] += len(results)
            c["redirect_results"] += sum(redirect(r["url"]) for r in results)
            err = pq.get("search_error")
            if err is not None:
                if account_side(err):
                    c["account_errors"] += 1
                    continue
                c["service_errors"] += 1
            obs[eng][(bucket, target)][syntax] = err is None and pq.get("hit_rank") is not None

engines = sorted(obs)
summary = {}
for eng in engines:
    summary[eng] = {}
    for bucket in BUCKET_ORDER:
        targets = [t for (b, t) in obs[eng] if b == bucket]
        if not targets:
            continue
        plain = [obs[eng][(bucket, t)].get("plain") for t in targets]
        plain = [p for p in plain if p is not None]
        cell = {"plain": sum(plain) / len(plain) if plain else None, "n": len(plain)}
        for v in VARIANTS:
            diffs = []
            for t in targets:
                d = obs[eng][(bucket, t)]
                if "plain" in d and v in d:
                    diffs.append(int(d[v]) - int(d["plain"]))
            if not diffs:
                continue
            boots = []
            for _ in range(2000):
                s = [diffs[rng.randrange(len(diffs))] for _ in diffs]
                boots.append(sum(s) / len(s))
            cell[v] = {"mean": sum(diffs) / len(diffs), "lo": pct(boots, .025), "hi": pct(boots, .975), "n": len(diffs), "var_recall": sum(int(obs[eng][(bucket, t)][v]) for t in targets if v in obs[eng][(bucket, t)]) / len(diffs)}
        cell["counts"] = dict(sorted(counts[eng][bucket].items()))
        summary[eng][bucket] = cell
    total = sum(counts[eng].values(), collections.Counter())
    summary[eng]["redirect_share"] = total["redirect_results"] / total["results"] if total["results"] else 0.0


def failures(eng, bucket):
    return counts[eng][bucket]["account_errors"] + counts[eng][bucket]["service_errors"]


def pool(bucket, v, engs):
    engs = [e for e in engs if bucket in summary[e] and v in summary[e][bucket]]
    if not engs:
        return None
    cells = [summary[e][bucket][v] for e in engs]
    means = [c["mean"] for c in cells]
    return {"engine_mean": sum(means) / len(means), "min": min(means), "max": max(means), "engines": len(cells),
            "sig_down": sum(c["hi"] < 0 for c in cells), "sig_up": sum(c["lo"] > 0 for c in cells),
            "plain_mean": sum(summary[e][bucket]["plain"] for e in engs) / len(engs)}


subsets = {"all": lambda b: engines, "no_redirect": lambda b: [e for e in engines if summary[e]["redirect_share"] <= REDIRECT_MIN],
           "no_failures": lambda b: [e for e in engines if not failures(e, b)]}
pooled = {name: {b: {v: p for v in VARIANTS if (p := pool(b, v, sel(b)))} for b in BUCKET_ORDER} for name, sel in subsets.items()}
pooled_engines = {name: {b: [e for e in sel(b) if b in summary[e]] for b in BUCKET_ORDER} for name, sel in subsets.items()}
json.dump({"engines": summary, "redirect_min": REDIRECT_MIN, "pooled": pooled, "pooled_engines": pooled_engines}, open(out_json, "w"), indent=1)

print("engines", len(engines), "failures", {e: {b: dict(counts[e][b]) for b in BUCKET_ORDER if failures(e, b)} for e in engines if any(failures(e, b) for b in BUCKET_ORDER)})
for name in subsets:
    for bucket in BUCKET_ORDER:
        if pooled[name][bucket]:
            print(name, bucket, json.dumps(pooled[name][bucket]))
for eng in engines:
    line = [f"{eng:17s}"]
    for bucket in BUCKET_ORDER:
        c = summary[eng].get(bucket)
        if not c:
            continue
        line.append(f"{bucket[:4]} plain {c['plain']:.2f}" + "".join(f" {v[:2]} {c[v]['mean']:+.2f}[{c[v]['lo']:+.2f},{c[v]['hi']:+.2f}]" for v in VARIANTS if v in c))
    line.append(f"redirect {summary[eng]['redirect_share']:.2f}")
    print(" | ".join(line))
