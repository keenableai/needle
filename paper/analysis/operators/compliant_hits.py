import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

SITE_RE = re.compile(r"site:(\S+)")


def host_ok(url, site):
    h = (urlsplit(url).hostname or "").lower()
    return h == site or h.endswith("." + site)


def scan(hf_dir, report, qfile, bucket_of):
    hits = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))
    for run in sorted(p for p in Path(hf_dir).iterdir() if p.is_dir() and (p / report).exists()):
        buckets = {}
        for line in open(run / qfile):
            if line.strip():
                g = json.loads(line)
                buckets[g["query_text"]] = bucket_of(g)
        rep = json.load(open(run / report))
        for eng, e in rep["engines"].items():
            p = run / e.get("per_query_path", "")
            if eng == "ultimate" or not p.exists():
                continue
            for pq in json.load(open(p))["per_query"]:
                m = SITE_RE.search(pq["query"])
                if not m or pq.get("search_error") is not None or pq["query"] not in buckets:
                    continue
                site = m.group(1).lower().strip('"')
                b = buckets[pq["query"]]
                c = hits[b][eng]
                c[2] += 1
                if pq.get("hit_rank") is not None:
                    c[0] += 1
                    r = pq["results"][pq["hit_rank"] - 1]
                    c[1] += host_ok(r["url"], site)
    return hits


leg = scan(sys.argv[2], "legal.json", "legal.jsonl", lambda g: json.loads(g["query_origin"])["bucket"])
fin = scan(sys.argv[1], "recall.json", "gold.jsonl", lambda g: "filing" if g["gold"]["field"] == "filing" else "fact")
for name, d in (("caselaw", leg["caselaw"]), ("code", leg["code"]), ("filing", fin["filing"])):
    engs = sorted(d, key=lambda e: -d[e][0] / max(1, d[e][2]))
    tot = [sum(d[e][i] for e in d) for i in range(3)]
    print(f"{name}: queries/engine ~{tot[2]//len(d)}  mean recall {tot[0]/tot[2]:.3f}  compliant recall {tot[1]/tot[2]:.3f}")
    for e in engs:
        h, c, n = d[e]
        if h and (h - c) / h > 0.1:
            print(f"   {e:18s} recall {h/n:.2f} compliant {c/n:.2f}")
