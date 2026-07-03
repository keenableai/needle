"""Publish a bench run: summaries to gh-pages, full artifacts staged for the HF dataset.

gh-pages gets the small, append-only files the dashboard reads directly
(history.jsonl, latest_*.json, runs.json); the full per-run reports are
written to --runs-out/<run_id>/ for upload to the public HF dataset
(keenable-ai/keenbench-results), which the judgement browser fetches.

Usage: uv run python scripts/publish_bench.py --site <gh-pages checkout>
           --runs-out <staging dir> [--rbp rbp.json] [--fresh fresh.jsonl]
           [--recall recall.json] [--gold gold.jsonl] [--ts 2026-07-02T14:17Z]
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import fire

from keenbench.shared.io import write_json


def freshstream_rows(report: dict, ts: str) -> list[dict]:
    return [
        {
            "ts": ts,
            "bench": "freshstream",
            "engine": name,
            "rbp": e["mean_rbp"],
            "rbp_max": e["rbp_max"],
            "num_scored": e["num_scored"],
            "num_queries": report["num_queries"],
            "search_errors": e["search_errors"],
            "judge_errors": e["judge_errors"],
        }
        for name, e in report["engines"].items()
    ]


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
            "shallow_index": e["shallow_index"]["shallow_index_rate"],
            "title_recall": e["by_bucket"].get("title", {}).get("recall_at_k"),
            "body_recall": e["by_bucket"].get("body", {}).get("recall_at_k"),
            "num_scored": e["num_scored"],
            "num_queries": report["num_queries"],
            "search_errors": e["search_errors"],
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
    scholar: str | None = None,
    scholar_queries: str | None = None,
    ts: str | None = None,
) -> None:
    ts = ts or datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")
    run_id = ts.replace(":", "")
    data = Path(site) / "data"
    data.mkdir(parents=True, exist_ok=True)
    run_dir = Path(runs_out) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for path, to_rows, latest, archive_name in (
        (rbp, freshstream_rows, "latest_freshstream.json", "rbp.json"),
        (recall, companyfill_rows, "latest_companyfill.json", "recall.json"),
        (scholar, scholar_rows, "latest_scholar.json", "scholar.json"),
    ):
        if not path:
            continue
        raw = Path(path).read_text(encoding="utf-8")
        report = json.loads(raw)
        rows.extend(to_rows(report, ts))
        write_json(slim_report(report), str(data / latest))
        (run_dir / archive_name).write_text(raw, encoding="utf-8")
    for path, archive_name in (
        (fresh, "fresh.jsonl"),
        (gold, "gold.jsonl"),
        (scholar_queries, "scholar.jsonl"),
    ):
        if path:
            (run_dir / archive_name).write_bytes(Path(path).read_bytes())

    with open(data / "history.jsonl", "a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    index_path = data / "runs.json"
    runs = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
    runs.append({"id": run_id, "ts": ts, "artifacts": sorted(p.name for p in run_dir.iterdir())})
    write_json(runs, str(index_path))
    print(f"appended {len(rows)} rows at {ts}; staged {run_id}")


if __name__ == "__main__":
    fire.Fire(publish)
