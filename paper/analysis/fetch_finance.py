import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

runs_json, out_dir, since = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
BASE = "https://huggingface.co/datasets/keenable-ai/needle-results/resolve/main/runs"


def get(path, dest):
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(f"{BASE}/{path}", timeout=120) as r:
        dest.write_bytes(r.read())
    return dest


runs = [r for r in json.load(open(runs_json)) if "recall.json" in r["artifacts"] and r["ts"] >= since]
print(len(runs), "runs")
jobs = []
for r in runs:
    rid = r["id"]
    rep = json.load(open(get(f"{rid}/recall.json", out_dir / rid / "recall.json")))
    jobs.append((f"{rid}/gold.jsonl", out_dir / rid / "gold.jsonl"))
    for name, e in rep["engines"].items():
        if "per_query_path" in e:
            jobs.append((f"{rid}/{e['per_query_path']}", out_dir / rid / e["per_query_path"]))
print(len(jobs), "files")
with ThreadPoolExecutor(8) as pool:
    done = list(pool.map(lambda j: get(*j), jobs))
print("ok", len(done))
