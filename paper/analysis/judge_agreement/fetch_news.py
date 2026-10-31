import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ids_txt, out_dir, step = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
BASE = "https://huggingface.co/datasets/keenable-ai/needle-results/resolve/main/runs"


def get(path, dest):
    if dest.exists() and dest.stat().st_size > 20:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(f"{BASE}/{path}", timeout=120) as r:
                dest.write_bytes(r.read())
            return dest
        except Exception as e:
            err = e
    print("FAIL", path, err)
    return None


ids = [l.strip() for l in open(ids_txt) if l.strip()][::step]
print(len(ids), "runs", ids[0], ids[-1], flush=True)
jobs = []
for rid in ids:
    p = get(f"{rid}/ndcg.json", out_dir / rid / "ndcg.json")
    if p is None:
        continue
    rep = json.load(open(p))
    jobs.append((f"{rid}/fresh.jsonl", out_dir / rid / "fresh.jsonl"))
    for name, e in rep["engines"].items():
        if "per_query_path" in e:
            jobs.append((f"{rid}/{e['per_query_path']}", out_dir / rid / e["per_query_path"]))
print(len(jobs), "files", flush=True)
with ThreadPoolExecutor(8) as pool:
    done = [d for d in pool.map(lambda j: get(*j), jobs) if d]
print("ok", len(done))
