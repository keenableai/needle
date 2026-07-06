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
from datetime import UTC, datetime
from pathlib import Path

import fire

from keenbench.shared.io import append_jsonl, write_json
from keenbench.shared.overlap import TS_FMT, overlap_rows, uniqueness_rows


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
            "lat_ms": (e.get("latency") or {}).get("samples_ms"),
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
            "lat_ms": (e.get("latency") or {}).get("samples_ms"),
        }
        for name, e in report["engines"].items()
    ]


def scholar_rows(report: dict, ts: str) -> list[dict]:
    return [
        {
            "ts": ts,
            "bench": "scholar",
            "engine": name,
            "recall": e["recall_at_k"],
            "mrr": e["mrr_at_k"],
            "title_recall": e["by_bucket"].get("title", {}).get("recall_at_k"),
            "body_recall": e["by_bucket"].get("body", {}).get("recall_at_k"),
            "num_scored": e["num_scored"],
            "num_queries": report["num_queries"],
            "search_errors": e["search_errors"],
            "p50_ms": (e.get("latency") or {}).get("p50_ms"),
            "p95_ms": (e.get("latency") or {}).get("p95_ms"),
            "lat_ms": (e.get("latency") or {}).get("samples_ms"),
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
    scholar: str | None = None,
    scholar_queries: str | None = None,
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
    uniqueness = []
    for path, to_rows, latest, archive_name in (
        (rbp, freshstream_rows, "latest_freshstream.json", "rbp.json"),
        (recall, companyfill_rows, "latest_companyfill.json", "recall.json"),
        (rarestream, rarestream_rows, "latest_rarestream.json", "rarestream.json"),
        (scholar, scholar_rows, "latest_scholar.json", "scholar.json"),
    ):
        if not path:
            continue
        raw = Path(path).read_text(encoding="utf-8")
        report = json.loads(raw)
        rows.extend(to_rows(report, ts))
        overlap.extend(overlap_rows(report, ts=ts))
        uniqueness.extend(uniqueness_rows(report, ts=ts))
        write_json(slim_report(report), str(data / latest))
        (run_dir / archive_name).write_text(raw, encoding="utf-8")
    for path, archive_name in (
        (fresh, "fresh.jsonl"),
        (gold, "gold.jsonl"),
        (scholar_queries, "scholar.jsonl"),
    ):
        if path:
            (run_dir / archive_name).write_bytes(Path(path).read_bytes())

    append_jsonl(rows, str(data / "history.jsonl"))
    for name, new_rows in (("overlap.jsonl", overlap), ("uniqueness.jsonl", uniqueness)):
        append_jsonl(new_rows, str(data / name))

    index_path = data / "runs.json"
    runs = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
    runs.append({"id": run_id, "ts": ts, "artifacts": sorted(p.name for p in run_dir.iterdir())})
    write_json(runs, str(index_path))
    print(f"appended {len(rows)} rows at {ts}; staged {run_id}")


if __name__ == "__main__":
    fire.Fire(publish)
