import json
from datetime import UTC, datetime
from pathlib import Path

import fire

from keenbench.scholar.generate import QUERY_BUCKETS
from keenbench.shared.ci import ci_payload, score_row, updated_scores
from keenbench.shared.io import append_jsonl, load_jsonl, write_json, write_jsonl
from keenbench.shared.overlap import FAMILIES, TS_FMT, overlap_rows, uniqueness_rows


def _latency_fields(e: dict) -> dict:
    latency = e.get("latency") or {}
    return {
        "p50_ms": latency.get("p50_ms"),
        "p95_ms": latency.get("p95_ms"),
        "lat_ms": latency.get("samples_ms"),
    }


def _ndcg_rows(report: dict, ts: str, bench: str) -> list[dict]:
    return [
        {
            "ts": ts,
            "bench": bench,
            "engine": name,
            "ndcg": e["mean_ndcg"],
            "num_scored": e["num_scored"],
            "num_queries": report["num_queries"],
            "search_errors": e["search_errors"],
            "judge_errors": e["judge_errors"],
            **_latency_fields(e),
        }
        for name, e in report["engines"].items()
    ]


def news_rows(report: dict, ts: str) -> list[dict]:
    return _ndcg_rows(report, ts, "news")


def agentic_rare_rows(report: dict, ts: str) -> list[dict]:
    return _ndcg_rows(report, ts, "agentic_rare")


def scholar_rows(report: dict, ts: str) -> list[dict]:
    rows = []
    for name, e in report["engines"].items():
        row = {
            "ts": ts,
            "bench": "scholar",
            "engine": name,
            "recall": e["recall_at_k"],
            "mrr": e["mrr_at_k"],
        }
        for b in QUERY_BUCKETS:
            bucket = e["by_bucket"].get(b, {})
            row[f"{b}_recall"] = bucket.get("recall_at_k")
            row[f"{b}_n"] = bucket.get("n")
        row.update(
            {
                "num_scored": e["num_scored"],
                "num_queries": report["num_queries"],
                "search_errors": e["search_errors"],
                **_latency_fields(e),
            }
        )
        rows.append(row)
    return rows


def _suite_rows(report: dict, ts: str, bench: str, suites: tuple[str, str]) -> list[dict]:
    rows = []
    for name, e in report["engines"].items():
        rows.append(
            {
                "ts": ts,
                "bench": bench,
                "engine": name,
                "recall": e["recall_at_k"],
                "mrr": e["mrr_at_k"],
                f"{suites[0]}_recall": e["by_bucket"].get(suites[0], {}).get("recall_at_k"),
                f"{suites[0]}_n": e["by_bucket"].get(suites[0], {}).get("n"),
                f"{suites[1]}_recall": e["by_bucket"].get(suites[1], {}).get("recall_at_k"),
                f"{suites[1]}_n": e["by_bucket"].get(suites[1], {}).get("n"),
                "num_scored": e["num_scored"],
                "num_queries": report["num_queries"],
                "search_errors": e["search_errors"],
                **_latency_fields(e),
            }
        )
    return rows


def finance_rows(report: dict, ts: str) -> list[dict]:
    return _suite_rows(report, ts, "finance", ("filings", "filingdoc"))


def legal_rows(report: dict, ts: str) -> list[dict]:
    return _suite_rows(report, ts, "legal", ("caselaw", "code"))


def slim_report(report: dict) -> dict:
    slim = dict(report)
    slim["engines"] = {
        name: {k: v for k, v in e.items() if k != "per_query"}
        for name, e in report["engines"].items()
    }
    return slim


def _publish_rows(path: Path, new_rows: list[dict], ts: str, republish: bool) -> None:
    if republish and path.exists():
        kept = [row for row in load_jsonl(path) if row["ts"] != ts]
        write_jsonl(kept + new_rows, str(path))
    else:
        append_jsonl(new_rows, str(path))


def publish(
    site: str,
    runs_out: str,
    ndcg: str | None = None,
    fresh: str | None = None,
    recall: str | None = None,
    gold: str | None = None,
    agentic_rare: str | None = None,
    agentic_rare_queries: str | None = None,
    scholar: str | None = None,
    scholar_queries: str | None = None,
    legal: str | None = None,
    legal_queries: str | None = None,
    ts: str | None = None,
) -> None:
    ts = ts or datetime.now(UTC).strftime(TS_FMT)
    run_id = ts.replace(":", "")
    data = Path(site) / "data"
    data.mkdir(parents=True, exist_ok=True)
    write_json(FAMILIES, str(data / "families.json"))
    run_dir = Path(runs_out) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    overlap = []
    uniqueness = []
    score_rows = []
    for bench, path, to_rows, latest, archive_name in (
        ("news", ndcg, news_rows, "latest_news.json", "ndcg.json"),
        ("finance", recall, finance_rows, "latest_finance.json", "recall.json"),
        (
            "agentic_rare",
            agentic_rare,
            agentic_rare_rows,
            "latest_agentic_rare.json",
            "agentic_rare.json",
        ),
        ("scholar", scholar, scholar_rows, "latest_scholar.json", "scholar.json"),
        ("legal", legal, legal_rows, "latest_legal.json", "legal.json"),
    ):
        if not path:
            continue
        raw = Path(path).read_text(encoding="utf-8")
        report = json.loads(raw)
        rows.extend(to_rows(report, ts))
        overlap.extend(overlap_rows(report, ts=ts))
        uniqueness.extend(uniqueness_rows(report, ts=ts))
        score_rows.append(score_row(report, bench, ts))
        write_json(slim_report(report), str(data / latest))
        (run_dir / archive_name).write_text(raw, encoding="utf-8")
    for path, archive_name in (
        (fresh, "fresh.jsonl"),
        (gold, "gold.jsonl"),
        (agentic_rare_queries, "agentic_rare.jsonl"),
        (scholar_queries, "scholar.jsonl"),
        (legal_queries, "legal.jsonl"),
    ):
        if path:
            (run_dir / archive_name).write_bytes(Path(path).read_bytes())

    index_path = data / "runs.json"
    runs = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
    republish = any(r.get("id") == run_id for r in runs)

    _publish_rows(data / "history.jsonl", rows, ts, republish)
    for name, new_rows in (("overlap.jsonl", overlap), ("uniqueness.jsonl", uniqueness)):
        _publish_rows(data / name, new_rows, ts, republish)

    scores = updated_scores(load_jsonl(data / "ci_scores.jsonl"), score_rows, ts)
    if scores:
        write_jsonl(scores, str(data / "ci_scores.jsonl"))
        write_json(ci_payload(scores, max(r["ts"] for r in scores)), str(data / "ci.json"))

    runs = [r for r in runs if r.get("id") != run_id]
    runs.append({"id": run_id, "ts": ts, "artifacts": sorted(p.name for p in run_dir.iterdir())})
    write_json(runs, str(index_path))
    print(f"appended {len(rows)} rows at {ts}; staged {run_id}")


if __name__ == "__main__":
    fire.Fire(publish)
