import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import fire
import httpx

from keenbench.shared.io import write_jsonl
from keenbench.shared.overlap import TS_FMT, overlap_rows, uniqueness_rows

DEFAULT_DATASET = "keenable-ai/keenbench-results"
ARTIFACTS = (
    ("rbp.json",),
    ("recall.json",),
    ("agentic_rare.json", "rarestream.json"),
    ("scholar.json",),
    ("legal.json",),
)


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _done(rows: list[dict], fields: tuple[str, ...]) -> set[str]:
    stale = {r["ts"] for r in rows if any(f not in r for f in fields)}
    return {r["ts"] for r in rows} - stale


def _merge_write(existing: list[dict], new: list[dict], path: Path) -> None:
    redone = {r["ts"] for r in new}
    write_jsonl([r for r in existing if r["ts"] not in redone] + new, str(path))


def backfill(site: str, hours: int | None = None, dataset: str | None = None) -> None:
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
    overlap = _load(data / "overlap.jsonl")
    uniqueness = _load(data / "uniqueness.jsonl")
    overlap_done = _done(overlap, ("num_shared3", "num_suspect", "low_shared_urls"))
    uniqueness_done = _done(uniqueness, ("relevant_unique_urls", "relevant_total_urls"))
    cutoff = (
        (datetime.now(UTC) - timedelta(hours=hours)).strftime(TS_FMT) if hours is not None else ""
    )

    new_overlap: list[dict] = []
    new_uniqueness: list[dict] = []
    n_runs = 0
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        for run in runs:
            want_overlap = run["ts"] not in overlap_done
            want_uniqueness = run["ts"] not in uniqueness_done
            if not (want_overlap or want_uniqueness) or run["ts"] < cutoff:
                continue
            n_runs += 1
            for group in ARTIFACTS:
                artifact = next((a for a in group if a in run["artifacts"]), None)
                if artifact is None:
                    continue
                resp = client.get(f"{runs_base}/{run['id']}/{artifact}")
                resp.raise_for_status()
                report = resp.json()
                if want_overlap:
                    new_overlap.extend(overlap_rows(report, ts=run["ts"]))
                if want_uniqueness:
                    new_uniqueness.extend(uniqueness_rows(report, ts=run["ts"]))

    if not (new_overlap or new_uniqueness):
        print("nothing to backfill")
        return
    if new_overlap:
        _merge_write(overlap, new_overlap, data / "overlap.jsonl")
    if new_uniqueness:
        _merge_write(uniqueness, new_uniqueness, data / "uniqueness.jsonl")
    print(f"backfilled {len(new_overlap) + len(new_uniqueness)} rows from {n_runs} runs")


if __name__ == "__main__":
    fire.Fire(backfill)
