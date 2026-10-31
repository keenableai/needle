import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

dirs = {"news": ("ndcg.json", sys.argv[1]), "finance": ("recall.json", sys.argv[2]), "legal": ("legal.json", sys.argv[3]), "rare": ("agentic_rare.json", sys.argv[4])}
cat = defaultdict(Counter)
total = Counter()


def bucket(err):
    t = err.get("error_type")
    msg = err.get("error_message") or ""
    if t == "transport":
        return "timeout" if "Timeout" in msg else "transport"
    m = re.match(r"(\d{3})", msg)
    if not m:
        return t
    c = int(m.group(1))
    if c == 429:
        return "429"
    if c in (401, 402, 403):
        return "401-403"
    if 400 <= c < 500:
        return "other 4xx"
    return "5xx"


for bench, (report, d) in dirs.items():
    for run in sorted(p for p in Path(d).iterdir() if p.is_dir() and (p / report).exists()):
        rep = json.load(open(run / report))
        for eng, e in rep["engines"].items():
            p = run / e.get("per_query_path", "")
            if eng == "ultimate" or not p.exists():
                continue
            for pq in json.load(open(p))["per_query"]:
                total[eng] += 1
                if pq.get("search_error"):
                    cat[eng][bucket(pq["search_error"])] += 1
allc = Counter()
for e in cat:
    allc.update(cat[e])
print("overall", allc.most_common())
for eng in sorted(cat, key=lambda e: -sum(cat[e].values())):
    n = sum(cat[eng].values())
    if n >= 20:
        print(f"{eng:18s} {100*n/total[eng]:5.1f}%", dict(cat[eng].most_common(3)))
