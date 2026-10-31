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


def scan(hf_dir, report_name, queries_name):
    comp = defaultdict(lambda: [0, 0])
    nres = defaultdict(int)
    for run in sorted(p for p in Path(hf_dir).iterdir() if p.is_dir() and (p / report_name).exists()):
        rep = json.load(open(run / report_name))
        for eng, e in rep["engines"].items():
            p = run / e.get("per_query_path", "")
            if eng == "ultimate" or not p.exists():
                continue
            for pq in json.load(open(p))["per_query"]:
                m = SITE_RE.search(pq["query"])
                if not m or pq.get("search_error") is not None:
                    continue
                site = m.group(1).lower().strip('"')
                for r in pq["results"]:
                    comp[eng][0] += host_ok(r["url"], site)
                    comp[eng][1] += 1
                nres[eng] += 1
    return comp


fin = scan(sys.argv[1], "recall.json", "gold.jsonl")
leg = scan(sys.argv[2], "legal.json", "legal.jsonl")
engines = sorted(set(fin) | set(leg), key=lambda e: -(fin.get(e, [0, 1])[0] / max(1, fin.get(e, [0, 1])[1])))
print(f"{'engine':18s} {'finance site:sec.gov':>22s} {'legal site:':>14s}")
allf = [0, 0]
alll = [0, 0]
for e in engines:
    f = fin.get(e, [0, 0])
    l = leg.get(e, [0, 0])
    allf[0] += f[0]; allf[1] += f[1]; alll[0] += l[0]; alll[1] += l[1]
    fs = f"{f[0]/f[1]:.2f} ({f[1]})" if f[1] else "-"
    ls = f"{l[0]/l[1]:.2f} ({l[1]})" if l[1] else "-"
    print(f"{e:18s} {fs:>22s} {ls:>14s}")
print("overall finance %.3f legal %.3f" % (allf[0] / allf[1], alll[0] / alll[1]))
