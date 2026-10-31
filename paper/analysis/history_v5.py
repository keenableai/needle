import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import REPORT_FILES, classify, run_dirs  # noqa: E402

site, history, out_history, out_unsplit = sys.argv[1:5]
runs = run_dirs(site)
lines = open(history).readlines()
rows = [json.loads(line) for line in lines]
new, unsplit = classify([r for r in rows if r["bench"] in REPORT_FILES], runs)
new = iter(new)
changed = Counter()
with open(out_history, "w") as f:
    for line, r in zip(lines, rows, strict=True):
        if r["bench"] in REPORT_FILES:
            n = next(new)
            if n != r:
                line = json.dumps(n) + "\n"
                changed[r["bench"], "rescored" if any(n.get(k) != r.get(k) for k in r) else "split"] += 1
        f.write(line)
json.dump([{k: r.get(k) for k in ("ts", "bench", "engine", "search_errors", "num_queries")} for r in unsplit], open(out_unsplit, "w"), indent=1)
print("runs with artifacts", len(runs), "lines changed", dict(changed), "rows with errors and no artifact", len(unsplit),
      dict(Counter(r["bench"] for r in unsplit)))
