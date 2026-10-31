import json
import urllib.request
from urllib.parse import urlsplit

BASE = "https://huggingface.co/datasets/keenable-ai/needle-results/resolve/main/runs"
runs = ["2026-10-29T2352Z", "2026-10-30T0117Z", "2026-10-30T0153Z", "2026-10-30T0256Z", "2026-10-30T0353Z", "2026-10-30T0451Z", "2026-10-30T0551Z", "2026-10-30T0706Z", "2026-10-30T0752Z", "2026-10-30T0902Z", "2026-10-30T0954Z", "2026-10-30T1053Z", "2026-10-30T1148Z", "2026-10-30T1303Z", "2026-10-30T1356Z", "2026-10-30T1456Z", "2026-10-30T1554Z", "2026-10-30T1654Z", "2026-10-30T1752Z", "2026-10-30T1854Z"]
for run in runs:
    rep = json.load(urllib.request.urlopen(f"{BASE}/{run}/ndcg.json", timeout=120))
    line = [run]
    for eng in ("google", "jina", "firecrawl"):
        e = rep["engines"].get(eng)
        if not e or "per_query_path" not in e:
            continue
        pq = json.load(urllib.request.urlopen(f"{BASE}/{run}/{e['per_query_path']}", timeout=120))["per_query"]
        n = g = 0
        for q in pq:
            for r in q.get("results") or []:
                n += 1
                g += "/goto" in urlsplit(r["url"]).path and "google.com" in (urlsplit(r["url"]).hostname or "")
        line.append(f"{eng} {g}/{n} ndcg {e.get('ndcg_at_k', e.get('ndcg', 0)) or 0:.3f}")
    print(" | ".join(line), flush=True)
