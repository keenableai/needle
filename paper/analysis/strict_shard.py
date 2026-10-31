import importlib.util
import json
import sys
from pathlib import Path

src, hf_dir, shard, nshards, out_json = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
sys.path.insert(0, src)
spec = importlib.util.spec_from_file_location("sfp", str(Path(__file__).parent / "strict_finance_par.py"))
sfp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sfp)

runs = sorted(str(p) for p in hf_dir.iterdir() if p.is_dir())[shard::nshards]
rows = []
for r in runs:
    rows.extend(sfp.process(r))
    print(r, "done", flush=True)
json.dump(rows, open(out_json, "w"))
print("shard", shard, "rows", len(rows))
