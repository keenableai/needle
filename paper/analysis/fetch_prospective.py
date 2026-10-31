import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

runs_json, out_dir = sys.argv[1], Path(sys.argv[2])
BASE = "https://huggingface.co/datasets/keenable-ai/needle-results/resolve/main/runs"
REPORTS = {"ndcg.json": "news", "agentic_rare.json": "agentic_rare", "scholar.json": "scholar", "legal.json": "legal", "recall.json": "finance"}
EXTRA = {"finance": ["gold.jsonl"], "legal": ["legal.jsonl"], "scholar": ["scholar.jsonl"]}


def get(path, dest):
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    err = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(f"{BASE}/{path}", timeout=120) as r:
                dest.write_bytes(r.read())
            return dest
        except Exception as e:
            err = e
            time.sleep(5 * (attempt + 1) if "429" in str(e) else 2)
    print("failed", path, err, flush=True)
    return None


jobs = []
for r in json.load(open(runs_json)):
    rid = r["id"]
    for report, bench in REPORTS.items():
        if report not in r["artifacts"]:
            continue
        p = get(f"{rid}/{report}", out_dir / bench / rid / report)
        if p is None:
            continue
        rep = json.load(open(p))
        for name, e in rep["engines"].items():
            if "per_query_path" in e:
                jobs.append((f"{rid}/{e['per_query_path']}", out_dir / bench / rid / e["per_query_path"]))
        for extra in EXTRA.get(bench, []):
            if extra in r["artifacts"]:
                jobs.append((f"{rid}/{extra}", out_dir / bench / rid / extra))
print(len(jobs), "files", flush=True)
with ThreadPoolExecutor(3) as pool:
    done = [d for d in pool.map(lambda j: get(*j), jobs) if d]
print("ok", len(done), flush=True)
