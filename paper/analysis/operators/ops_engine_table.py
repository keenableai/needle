import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

fin_dir, leg_dir, out_tex = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
NAMES = {
    "keenable": "Keenable", "exa": "Exa", "brave-llmcontext": "Brave (LLM ctx)", "perplexity": "Perplexity",
    "parallel": "Parallel", "brave": "Brave", "you": "You.com", "linkup": "Linkup", "deepseek": "DeepSeek",
    "context": "Context", "kagi": "Kagi", "firecrawl": "Firecrawl", "chatgpt-search": "ChatGPT search",
    "google": "Google (Serper)", "octen": "Octen", "bing": "Bing (SearchAPI)", "claude-search": "Claude search",
    "jina": "Jina", "tavily": "Tavily", "tinyfish": "TinyFish", "ceramic": "Ceramic",
}
SITE_RE = re.compile(r"site:(\S+)")
rec = defaultdict(lambda: defaultdict(lambda: [0, 0]))
comp = defaultdict(lambda: defaultdict(lambda: [0, 0]))


def host_ok(url, site):
    h = (urlsplit(url).hostname or "").lower()
    return h == site or h.endswith("." + site)


def scan(hf_dir, report, qfile, bench, keyfn):
    for run in sorted(p for p in hf_dir.iterdir() if p.is_dir() and (p / report).exists()):
        meta = {}
        for line in open(run / qfile):
            if line.strip():
                g = json.loads(line)
                k = keyfn(g)
                if k:
                    meta[g["query_text"]] = k
        rep = json.load(open(run / report))
        for eng, e in rep["engines"].items():
            p = run / e.get("per_query_path", "")
            if eng not in NAMES or not p.exists():
                continue
            for pq in json.load(open(p))["per_query"]:
                k = meta.get(pq["query"])
                if k is None or pq.get("search_error") is not None:
                    continue
                rec[eng][k][0] += pq.get("hit_rank") is not None
                rec[eng][k][1] += 1
                m = SITE_RE.search(pq["query"])
                if m:
                    site = m.group(1).lower()
                    for r in pq["results"]:
                        comp[eng][bench][0] += host_ok(r["url"], site)
                        comp[eng][bench][1] += 1


def fin_key(g):
    o = json.loads(g["query_origin"])
    if g["gold"]["field"] != "filing":
        return None
    return "filing/" + o.get("syntax", "plain")


def leg_key(g):
    o = json.loads(g["query_origin"])
    return o["bucket"] + "/" + o.get("syntax", "plain")


scan(fin_dir, "recall.json", "gold.jsonl", "fin", fin_key)
scan(leg_dir, "legal.json", "legal.jsonl", "leg", leg_key)
cols = ["caselaw/plain", "caselaw/site", "caselaw/date", "code/plain", "code/site", "filing/plain", "filing/site", "filing/date"]


def f(x):
    return "--" if x[1] == 0 else f"{x[0]/x[1]:.2f}"


order = sorted(NAMES, key=lambda e: -(rec[e]["caselaw/plain"][0] / max(1, rec[e]["caselaw/plain"][1])))
lines = []
for e in order:
    vals = [f(rec[e][c]) for c in cols]
    cvals = f(comp[e]["fin"]) + " / " + f(comp[e]["leg"])
    lines.append(f"{NAMES[e]} & " + " & ".join(vals) + f" & {cvals} \\\\")
open(out_tex, "w").write("\n".join(lines) + "\n")
print("rows", len(lines))
print("\n".join(lines[:3]))
