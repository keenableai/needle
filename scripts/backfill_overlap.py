"""Seed data/overlap.jsonl from runs already archived on the HF dataset.

publish_bench.py appends overlap rows going forward; this fills the window
before that started (e.g. runs published between seeding and merge). Runs
whose ts is already present in overlap.jsonl are skipped, so it composes
with the hourly appends and is a fetch-free no-op once caught up.

Usage: uv run python scripts/backfill_overlap.py --site <gh-pages checkout> [--hours 24]
"""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import fire
import httpx

from keenbench.shared.overlap import TS_FMT, WINDOW_HOURS, overlap_rows

DEFAULT_DATASET = "keenable-ai/keenbench-results"
ARTIFACTS = ("rbp.json", "recall.json")


def backfill(site: str, hours: int = WINDOW_HOURS, dataset: str | None = None) -> None:
    data = Path(site) / "data"
    index_path = data / "runs.json"
    if not index_path.exists():
        print("no runs.json yet; nothing to backfill")
        return
    runs = json.loads(index_path.read_text(encoding="utf-8"))
    runs_base = (
        "https://huggingface.co/datasets/"
        f"{dataset or os.environ.get('HF_DATASET', DEFAULT_DATASET)}/resolve/main/runs"
    )
    out_path = data / "overlap.jsonl"
    seen = set()
    if out_path.exists():
        seen = {
            json.loads(line)["ts"]
            for line in out_path.read_text(encoding="utf-8").splitlines()
            if line
        }
    cutoff = (datetime.now(UTC) - timedelta(hours=hours)).strftime(TS_FMT)

    rows = []
    n_runs = 0
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        for run in runs:
            if run["ts"] in seen or run["ts"] < cutoff:
                continue
            n_runs += 1
            for artifact in ARTIFACTS:
                if artifact not in run["artifacts"]:
                    continue
                resp = client.get(f"{runs_base}/{run['id']}/{artifact}")
                resp.raise_for_status()
                rows.extend(overlap_rows(resp.json(), ts=run["ts"]))

    if not rows:
        print("nothing to backfill")
        return
    with open(out_path, "a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"backfilled {len(rows)} rows from {n_runs} runs")


if __name__ == "__main__":
    fire.Fire(backfill)
