import collections
import json
import random
import re
import sys
from urllib.parse import urlsplit

out_json = sys.argv[1]
pairs = sys.argv[2:]
rng = random.Random(5)
SITE_RE = re.compile(r"site:(\S+)")
VARIANTS = ("quoted", "site", "date")
BUCKET_ORDER = ("caselaw", "code", "filing")


def host_ok(url, site):
    h = (urlsplit(url).hostname or "").lower()
    return h == site or h.endswith("." + site)


obs = collections.defaultdict(lambda: collections.defaultdict(dict))
compliance = collections.defaultdict(lambda: [0, 0])
errors = collections.Counter()
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
            if pq.get("search_error") is not None:
                errors[eng] += 1
                continue
            hit = pq.get("hit_rank") is not None
            m = SITE_RE.search(pq["query"])
            if m:
                site = m.group(1).lower()
                for r in pq.get("results") or []:
                    compliance[eng][0] += host_ok(r["url"], site)
                    compliance[eng][1] += 1
            obs[eng][(bucket, target)][syntax] = hit

engines = sorted(obs)
summary = {}
rows = {}
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
            boots.sort()
            cell[v] = {"mean": sum(diffs) / len(diffs), "lo": boots[int(0.025 * len(boots))], "hi": boots[int(0.975 * len(boots))], "n": len(diffs), "var_recall": sum(int(obs[eng][(bucket, t)][v]) for t in targets if v in obs[eng][(bucket, t)]) / len(diffs)}
        summary[eng][bucket] = cell
    summary[eng]["site_compliance"] = compliance[eng][0] / compliance[eng][1] if compliance[eng][1] else None
    summary[eng]["errors"] = errors[eng]

pooled = {}
for bucket in BUCKET_ORDER:
    pooled[bucket] = {}
    for v in VARIANTS:
        means = [summary[e][bucket][v]["mean"] for e in engines if bucket in summary[e] and v in summary[e][bucket]]
        if means:
            sig_down = sum(1 for e in engines if bucket in summary[e] and v in summary[e][bucket] and summary[e][bucket][v]["hi"] < 0)
            sig_up = sum(1 for e in engines if bucket in summary[e] and v in summary[e][bucket] and summary[e][bucket][v]["lo"] > 0)
            pooled[bucket][v] = {"engine_mean": sum(means) / len(means), "min": min(means), "max": max(means), "engines": len(means), "sig_down": sig_down, "sig_up": sig_up}
json.dump({"engines": summary, "pooled": pooled}, open(out_json, "w"), indent=1)

print("engines", len(engines), "errors", dict(errors))
for bucket in BUCKET_ORDER:
    print(bucket, json.dumps(pooled[bucket]))
for eng in engines:
    line = [f"{eng:17s}"]
    for bucket in BUCKET_ORDER:
        c = summary[eng].get(bucket)
        if not c:
            continue
        line.append(f"{bucket[:4]} plain {c['plain']:.2f}" + "".join(f" {v[:2]} {c[v]['mean']:+.2f}[{c[v]['lo']:+.2f},{c[v]['hi']:+.2f}]" for v in VARIANTS if v in c))
    sc = summary[eng]["site_compliance"]
    line.append(f"site-host {sc:.2f}" if sc is not None else "")
    print(" | ".join(line))
