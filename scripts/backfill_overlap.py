"""Seed data/overlap.jsonl and data/uniqueness.jsonl from runs archived on the HF dataset.

publish_bench.py appends rows going forward; this fills the window before
that started (e.g. runs published between seeding and merge). Runs whose ts
is already present in an output file are skipped for it, so it composes
with the hourly appends and is a fetch-free no-op once caught up.

Usage: uv run python scripts/backfill_overlap.py --site <gh-pages checkout> [--hours 24]
"""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import fire
import httpx

from keenbench.shared.overlap import TS_FMT, WINDOW_HOURS, overlap_rows, uniqueness_rows

DEFAULT_DATASET = "keenable-ai/keenbench-results"
ARTIFACTS = ("rbp.json", "recall.json", "scholar.json")


def _seen(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {
        json.loads(line)["ts"] for line in path.read_text(encoding="utf-8").splitlines() if line
    }


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
    outputs = {
        data / "overlap.jsonl": overlap_rows,
        data / "uniqueness.jsonl": uniqueness_rows,
    }
    seen = {path: _seen(path) for path in outputs}
    cutoff = (datetime.now(UTC) - timedelta(hours=hours)).strftime(TS_FMT)

    rows = {path: [] for path in outputs}
    n_runs = 0
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        for run in runs:
            targets = [p for p in outputs if run["ts"] not in seen[p]]
            if not targets or run["ts"] < cutoff:
                continue
            n_runs += 1
            for artifact in ARTIFACTS:
                if artifact not in run["artifacts"]:
                    continue
                resp = client.get(f"{runs_base}/{run['id']}/{artifact}")
                resp.raise_for_status()
                report = resp.json()
                for path in targets:
                    rows[path].extend(outputs[path](report, ts=run["ts"]))

    total = sum(len(r) for r in rows.values())
    if not total:
        print("nothing to backfill")
        return
    for path, new_rows in rows.items():
        with open(path, "a", encoding="utf-8") as fh:
            for row in new_rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"backfilled {total} rows from {n_runs} runs")


if __name__ == "__main__":
    fire.Fire(backfill)
