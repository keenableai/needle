import importlib.util
import sys
from pathlib import Path

src = sys.argv[1]
sys.path.insert(0, src)
spec = importlib.util.spec_from_file_location("sv2", str(Path(__file__).parent / "strict_v2.py"))
mod = importlib.util.module_from_spec(spec)
sys.argv = [str(Path(__file__).parent / "strict_v2.py")] + sys.argv[1:]
spec.loader.exec_module(mod)
import json
hf_dir, shard, nshards, out_json = Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
runs = sorted(str(p) for p in hf_dir.iterdir() if p.is_dir())[shard::nshards]
rows, new = [], []
for r in runs:
    rr, nn = mod.process(r)
    rows.extend(rr)
    new.extend(nn)
    print(r, "done", "new hits so far", len(new), flush=True)
json.dump({"rows": rows, "new_hits": new}, open(out_json, "w"))
print("shard", shard, "rows", len(rows), "new hits", len(new))
