"""Seed data/overlap.jsonl from runs already archived on the HF dataset.

publish_bench.py appends overlap rows going forward; this rebuilds the
window before that started (or after a normalization change). Runs whose
ts is already present in overlap.jsonl are skipped, so it composes with
the hourly appends.

Usage: uv run python scripts/backfill_overlap.py --site <gh-pages checkout> [--hours 24]
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import fire
import httpx

from keenbench.shared.overlap import overlap_rows

RUNS_BASE = "https://huggingface.co/datasets/keenable-ai/keenbench-results/resolve/main/runs"
ARTIFACTS = (("rbp.json", "freshstream"), ("recall.json", "companyfill"))


def parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)


def backfill(site: str, hours: int = 24) -> None:
    data = Path(site) / "data"
    index_path = data / "runs.json"
    if not index_path.exists():
        print("no runs.json yet; nothing to backfill")
        return
    runs = json.loads(index_path.read_text(encoding="utf-8"))
    out_path = data / "overlap.jsonl"
    existing = []
    if out_path.exists():
        existing = [
            json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines() if line
        ]
    seen = {row["ts"] for row in existing}
    cutoff = datetime.now(UTC) - timedelta(hours=hours)

    rows = []
    n_runs = 0
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        for run in runs:
            if run["ts"] in seen or parse_ts(run["ts"]) < cutoff:
                continue
            n_runs += 1
            for artifact, bench in ARTIFACTS:
                if artifact not in run["artifacts"]:
                    continue
                resp = client.get(f"{RUNS_BASE}/{run['id']}/{artifact}")
                resp.raise_for_status()
                rows.extend(overlap_rows(resp.json(), ts=run["ts"], bench=bench))

    merged = sorted(existing + rows, key=lambda r: r["ts"])
    with open(out_path, "w", encoding="utf-8") as fh:
        for row in merged:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"backfilled {len(rows)} rows from {n_runs} runs; {len(merged)} total")


if __name__ == "__main__":
    fire.Fire(backfill)
