import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = json.loads((root / "paper/analysis/manifest.json").read_text())["dashboard_history"]
result = subprocess.run(
    ["git", "-C", str(root), "show", f"{source['revision']}:{source['path']}"],
    check=True, capture_output=True, text=True,
)
rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
rows = [r for r in rows if r["ts"] <= source["through"]]
for row in rows:
    row.pop("lat_ms", None)
Path(sys.argv[1]).write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))
print(f"Wrote {len(rows)} rows through {source['through']}")
