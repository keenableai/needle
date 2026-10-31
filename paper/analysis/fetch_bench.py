import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

runs_json, out_dir, report, since, until = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
BASE = "https://huggingface.co/datasets/keenable-ai/needle-results/resolve/main/runs"


def get(path, dest):
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
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


runs = [r for r in json.load(open(runs_json)) if report in r["artifacts"] and since <= r["ts"] < until]
print(len(runs), "runs", flush=True)
jobs = []
for r in runs:
    rid = r["id"]
    p = get(f"{rid}/{report}", out_dir / rid / report)
    if p is None:
        continue
    rep = json.load(open(p))
    for name, e in rep["engines"].items():
        if "per_query_path" in e:
            jobs.append((f"{rid}/{e['per_query_path']}", out_dir / rid / e["per_query_path"]))
print(len(jobs), "files", flush=True)
with ThreadPoolExecutor(3) as pool:
    done = [d for d in pool.map(lambda j: get(*j), jobs) if d]
print("ok", len(done), flush=True)
