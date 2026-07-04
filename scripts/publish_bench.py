"""Publish a bench run: summaries to gh-pages, full artifacts staged for the HF dataset.

gh-pages gets the small, append-only files the dashboard reads directly
(history.jsonl, latest_*.json, runs.json); the full per-run reports are
written to --runs-out/<run_id>/ for upload to the public HF dataset
(keenable-ai/keenbench-results), which the judgement browser fetches.

Usage: uv run python scripts/publish_bench.py --site <gh-pages checkout>
           --runs-out <staging dir> [--rbp rbp.json] [--fresh fresh.jsonl]
           [--recall recall.json] [--gold gold.jsonl] [--rarestream rarestream.json]
           [--ts 2026-07-02T14:17Z]
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import fire

from keenbench.shared.io import write_json, write_jsonl
from keenbench.shared.overlap import TS_FMT, WINDOW_HOURS, overlap_rows


def _rbp_rows(report: dict, ts: str, bench: str) -> list[dict]:
    return [
        {
            "ts": ts,
            "bench": bench,
            "engine": name,
            "rbp": e["mean_rbp"],
            "rbp_max": e["rbp_max"],
            "num_scored": e["num_scored"],
            "num_queries": report["num_queries"],
            "search_errors": e["search_errors"],
            "judge_errors": e["judge_errors"],
            "p50_ms": (e.get("latency") or {}).get("p50_ms"),
            "p95_ms": (e.get("latency") or {}).get("p95_ms"),
        }
        for name, e in report["engines"].items()
    ]


def freshstream_rows(report: dict, ts: str) -> list[dict]:
    return _rbp_rows(report, ts, "freshstream")


def rarestream_rows(report: dict, ts: str) -> list[dict]:
    return _rbp_rows(report, ts, "rarestream")


def companyfill_rows(report: dict, ts: str) -> list[dict]:
    return [
        {
            "ts": ts,
            "bench": "companyfill",
            "engine": name,
            "recall": e["recall_at_k"],
            "mrr": e["mrr_at_k"],
            "num_scored": e["num_scored"],
            "num_queries": report["num_queries"],
            "search_errors": e["search_errors"],
            "p50_ms": (e.get("latency") or {}).get("p50_ms"),
            "p95_ms": (e.get("latency") or {}).get("p95_ms"),
        }
        for name, e in report["engines"].items()
    ]


def slim_report(report: dict) -> dict:
    slim = dict(report)
    slim["engines"] = {
        name: {k: v for k, v in e.items() if k != "per_query"}
        for name, e in report["engines"].items()
    }
    return slim


def publish(
    site: str,
    runs_out: str,
    rbp: str | None = None,
    fresh: str | None = None,
    recall: str | None = None,
    gold: str | None = None,
    rarestream: str | None = None,
    ts: str | None = None,
) -> None:
    ts = ts or datetime.now(UTC).strftime(TS_FMT)
    run_id = ts.replace(":", "")
    data = Path(site) / "data"
    data.mkdir(parents=True, exist_ok=True)
    run_dir = Path(runs_out) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    overlap = []
    for path, to_rows, latest, archive_name in (
        (rbp, freshstream_rows, "latest_freshstream.json", "rbp.json"),
        (recall, companyfill_rows, "latest_companyfill.json", "recall.json"),
        (rarestream, rarestream_rows, "latest_rarestream.json", "rarestream.json"),
    ):
        if not path:
            continue
        raw = Path(path).read_text(encoding="utf-8")
        report = json.loads(raw)
        rows.extend(to_rows(report, ts))
        overlap.extend(overlap_rows(report, ts=ts))
        write_json(slim_report(report), str(data / latest))
        (run_dir / archive_name).write_text(raw, encoding="utf-8")
    for path, archive_name in ((fresh, "fresh.jsonl"), (gold, "gold.jsonl")):
        if path:
            (run_dir / archive_name).write_bytes(Path(path).read_bytes())

    with open(data / "history.jsonl", "a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    # the dashboard reads only a trailing window of overlap, so prune on rewrite
    # instead of growing forever like history.jsonl (whose full range the charts use)
    overlap_path = data / "overlap.jsonl"
    kept = []
    if overlap_path.exists():
        cutoff_dt = datetime.strptime(ts, TS_FMT).replace(tzinfo=UTC) - timedelta(
            hours=WINDOW_HOURS
        )
        cutoff = cutoff_dt.strftime(TS_FMT)
        kept = [
            row
            for line in overlap_path.read_text(encoding="utf-8").splitlines()
            if line and (row := json.loads(line))["ts"] >= cutoff
        ]
    write_jsonl(kept + overlap, str(overlap_path))

    index_path = data / "runs.json"
    runs = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
    runs.append({"id": run_id, "ts": ts, "artifacts": sorted(p.name for p in run_dir.iterdir())})
    write_json(runs, str(index_path))
    print(f"appended {len(rows)} rows at {ts}; staged {run_id}")


if __name__ == "__main__":
    fire.Fire(publish)
