import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

runs_json, out_dir, bench, n_runs = sys.argv[1], Path(sys.argv[2]), sys.argv[3], int(sys.argv[4])
BASE = "https://huggingface.co/datasets/keenable-ai/needle-results/resolve/main/runs"


def get(path, dest):
    if dest.exists() and dest.stat().st_size > 20:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(6):
        try:
            with urllib.request.urlopen(f"{BASE}/{path}", timeout=120) as r:
                dest.write_bytes(r.read())
            return dest
        except urllib.error.HTTPError as e:
            if e.code != 429:
                print("FAIL", path, e)
                return None
            time.sleep(30 * (attempt + 1))
        except (ConnectionError, OSError) as e:
            time.sleep(10 * (attempt + 1))
    print("FAIL", path, "429")
    return None


ids = [r["id"] for r in json.load(open(runs_json)) if f"{bench}.json" in r["artifacts"]][-n_runs:]
print(len(ids), "runs", ids[0], ids[-1], flush=True)
jobs = []
for rid in ids:
    p = get(f"{rid}/{bench}.json", out_dir / rid / f"{bench}.json")
    if p is None:
        continue
    rep = json.load(open(p))
    jobs.append((f"{rid}/{bench}.jsonl", out_dir / rid / f"{bench}.jsonl"))
    for name, e in rep["engines"].items():
        if "per_query_path" in e:
            jobs.append((f"{rid}/{e['per_query_path']}", out_dir / rid / e["per_query_path"]))
print(len(jobs), "files", flush=True)
with ThreadPoolExecutor(4) as pool:
    done = [d for d in pool.map(lambda j: get(*j), jobs) if d]
print("ok", len(done))
