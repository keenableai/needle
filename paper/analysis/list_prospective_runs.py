import json
import sys

from huggingface_hub import HfApi

since, out = sys.argv[1], sys.argv[2]
api = HfApi()
repo = "keenable-ai/needle-results"
names = sorted(e.path for e in api.list_repo_tree(repo, path_in_repo="runs", repo_type="dataset"))
sel = [n for n in names if n.rsplit("/", 1)[1] >= since]
runs = []
for n in sel:
    files = sorted(e.path.rsplit("/", 1)[-1] for e in api.list_repo_tree(repo, path_in_repo=n, repo_type="dataset"))
    rid = n.rsplit("/", 1)[1]
    arts = [f for f in files if f.endswith(".json") or f.endswith(".jsonl")]
    ts = rid[:13] + ":" + rid[13:15] + "Z"
    runs.append({"id": rid, "ts": ts, "artifacts": arts})
    print(rid, arts, flush=True)
json.dump(runs, open(out, "w"), indent=1)
print(len(runs), "runs since", since)
