import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import SITE_RE, host_ok


def scan(hf_dir, report_name):
    comp = defaultdict(lambda: [0, 0])
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
    return comp


fin = scan(sys.argv[1], "recall.json")
leg = scan(sys.argv[2], "legal.json")
engines = sorted(sorted(set(fin) | set(leg)), key=lambda e: -(fin.get(e, [0, 1])[0] / max(1, fin.get(e, [0, 1])[1])))
print(f"{'engine':18s} {'finance site:sec.gov':>22s} {'legal site:':>14s}")
for e in engines:
    f = fin.get(e, [0, 0])
    g = leg.get(e, [0, 0])
    fs = f"{f[0]/f[1]:.2f} ({f[1]})" if f[1] else "-"
    gs = f"{g[0]/g[1]:.2f} ({g[1]})" if g[1] else "-"
    print(f"{e:18s} {fs:>22s} {gs:>14s}")
allf = [sum(c[i] for c in fin.values()) for i in (0, 1)]
alll = [sum(c[i] for c in leg.values()) for i in (0, 1)]
print(f"overall finance {allf[0] / allf[1]:.3f} legal {alll[0] / alll[1]:.3f}")
