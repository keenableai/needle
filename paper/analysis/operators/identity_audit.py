import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

scholar_dir, legal_dir = Path(sys.argv[1]), Path(sys.argv[2])


def host(u):
    return (urlsplit(u).hostname or "").lower().removeprefix("www.")


def scan(hf_dir, report, per_dir, gold_file):
    hits = Counter()
    hosts = Counter()
    in_url = 0
    total = 0
    for run in sorted(p for p in hf_dir.iterdir() if p.is_dir() and (p / report).exists()):
        gold = {}
        for line in open(run / gold_file):
            if line.strip():
                g = json.loads(line)
                gold[g["query_text"]] = json.loads(g["gold"]) if isinstance(g["gold"], str) else g["gold"]
        rep = json.load(open(run / report))
        for eng, e in rep["engines"].items():
            p = run / e.get("per_query_path", "")
            if eng == "ultimate" or not p.exists():
                continue
            for pq in json.load(open(p))["per_query"]:
                if pq.get("hit_rank") is None:
                    continue
                r = pq["results"][pq["hit_rank"] - 1]
                g = gold.get(pq["query"], {})
                ids = g.get("ids", {})
                tokens = []
                for k, v in ids.items():
                    for x in (v if isinstance(v, list) else [v]):
                        x = str(x)
                        tokens.append(x)
                        if k == "cfr":
                            t, sec = x.split(":")
                            tokens.append(f"title-{t}/section-{sec}")
                            tokens.append(f"title-{t}/part-{sec.split('.')[0]}/section-{sec}")
                        if k == "docket":
                            tokens.append(x.lower())
                url = r["url"].lower()
                total += 1
                hit_url = any(tok.lower() in url for tok in tokens if tok)
                in_url += hit_url
                hosts[host(r["url"])] += 1
    print(f"{report}: hits {total}, id in URL {in_url} ({in_url/total:.3f})")
    print("  top hosts:", hosts.most_common(12))


scan(scholar_dir, "scholar.json", "scholar", "scholar.jsonl")
scan(legal_dir, "legal.json", "legal", "legal.jsonl")
