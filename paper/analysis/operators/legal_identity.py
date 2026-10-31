import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

PRIMARY = ("law.cornell.edu", "ecfr.gov", "ecfr.io", "govinfo.gov", "courtlistener.com", "supremecourt.gov",
           "uscourts.gov", "justia.com", "findlaw.com", "casetext.com", "federalregister.gov", "regulations.gov",
           "vlex.com", "leagle.com", "govregs.com", "casemine.com", "anylaw.com")
tot = Counter()
inurl = Counter()
prim = Counter()
hosts = {"caselaw": Counter(), "code": Counter()}
for run in sorted(p for p in Path(sys.argv[1]).iterdir() if p.is_dir()):
    gold = {}
    for line in open(run / "legal.jsonl"):
        if line.strip():
            g = json.loads(line)
            gold[g["query_text"]] = (json.loads(g["query_origin"])["bucket"], json.loads(g["gold"]))
    rep = json.load(open(run / "legal.json"))
    for eng, e in rep["engines"].items():
        p = run / e.get("per_query_path", "")
        if eng == "ultimate" or not p.exists():
            continue
        for pq in json.load(open(p))["per_query"]:
            if pq.get("hit_rank") is None or pq["query"] not in gold:
                continue
            bucket, g = gold[pq["query"]]
            r = pq["results"][pq["hit_rank"] - 1]
            url = r["url"].lower()
            h = urlsplit(url).hostname or ""
            tot[bucket] += 1
            if bucket == "code":
                sec = g["ids"]["cfr"].split(":")[1]
                inurl[bucket] += sec in url
            else:
                ids = g["ids"]
                toks = [str(ids.get("cluster", "")), str(ids.get("docket", "")).lower()] + [c.lower().replace(" ", "") for c in ids.get("cites", [])]
                inurl[bucket] += any(t and t in url.replace(" ", "") for t in toks)
            prim[bucket] += any(h == d or h.endswith("." + d) for d in PRIMARY)
            hosts[bucket][h] += 1
for b in tot:
    print(b, "hits", tot[b], "id in URL %.3f" % (inurl[b] / tot[b]), "primary legal host %.3f" % (prim[b] / tot[b]))
    print("   non-primary hosts:", [(h, n) for h, n in hosts[b].most_common(60) if not any(h == d or h.endswith("." + d) for d in PRIMARY)][:12])
