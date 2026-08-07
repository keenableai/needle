import json
from datetime import UTC, datetime
from pathlib import Path

import fire

from keenbench.scholar.generate import QUERY_BUCKETS
from keenbench.shared.io import append_jsonl, write_json, write_jsonl
from keenbench.shared.overlap import FAMILIES, TS_FMT, overlap_rows, uniqueness_rows


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


def news_rows(report: dict, ts: str) -> list[dict]:
    return _rbp_rows(report, ts, "news")


def agentic_rare_rows(report: dict, ts: str) -> list[dict]:
    return _rbp_rows(report, ts, "agentic_rare")


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
                "p50_ms": (e.get("latency") or {}).get("p50_ms"),
                "p95_ms": (e.get("latency") or {}).get("p95_ms"),
                "lat_ms": (e.get("latency") or {}).get("samples_ms"),
            }
        )
        rows.append(row)
    return rows


def _syntax_split(e: dict) -> tuple[float | None, float | None]:
    groups = e.get("by_syntax") or {}
    plain = groups.get("plain", {}).get("recall_at_k")
    ops = [(g["n"], g["recall_at_k"]) for name, g in groups.items() if name != "plain"]
    total = sum(n for n, _ in ops)
    op = sum(n * r for n, r in ops) / total if total else None
    return plain, op


def _suite_rows(report: dict, ts: str, bench: str, suites: tuple[str, str]) -> list[dict]:
    rows = []
    for name, e in report["engines"].items():
        plain_recall, op_recall = _syntax_split(e)
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
                "plain_recall": plain_recall,
                "op_recall": op_recall,
                "num_scored": e["num_scored"],
                "num_queries": report["num_queries"],
                "search_errors": e["search_errors"],
                "p50_ms": (e.get("latency") or {}).get("p50_ms"),
                "p95_ms": (e.get("latency") or {}).get("p95_ms"),
                "lat_ms": (e.get("latency") or {}).get("samples_ms"),
            }
        )
    return rows


def finance_rows(report: dict, ts: str) -> list[dict]:
    return _suite_rows(report, ts, "finance", ("filings", "filingdoc"))


def legal_rows(report: dict, ts: str) -> list[dict]:
    return _suite_rows(report, ts, "legal", ("caselaw", "code"))


def findallmcp_rows(report: dict, ts: str) -> list[dict]:
    return [
        {
            "ts": ts,
            "bench": "findallmcp",
            "engine": name,
            "score": e["mean_score"],
            "set_recall": e["set_recall"],
            "set_precision": e["set_precision"],
            "stat_score": e["stat_score"],
            "spent_usd": e["mean_spent_usd"],
            "tool_calls": e["mean_tool_calls"],
            "num_scored": e["num_scored"],
            "num_queries": report["num_queries"],
            "search_errors": e["errors"],
        }
        for name, e in report["backends"].items()
    ]


def slim_report(report: dict, key: str = "engines") -> dict:
    slim = dict(report)
    slim[key] = {
        name: {k: v for k, v in e.items() if k != "per_query"} for name, e in report[key].items()
    }
    return slim


def _publish_rows(path: Path, new_rows: list[dict], ts: str, republish: bool) -> None:
    if republish and path.exists():
        kept = [
            row
            for line in path.read_text(encoding="utf-8").splitlines()
            if line and (row := json.loads(line))["ts"] != ts
        ]
        write_jsonl(kept + new_rows, str(path))
    else:
        append_jsonl(new_rows, str(path))


def publish(
    site: str,
    runs_out: str,
    rbp: str | None = None,
    fresh: str | None = None,
    recall: str | None = None,
    gold: str | None = None,
    agentic_rare: str | None = None,
    agentic_rare_queries: str | None = None,
    scholar: str | None = None,
    scholar_queries: str | None = None,
    legal: str | None = None,
    legal_queries: str | None = None,
    findallmcp: str | None = None,
    findallmcp_queries: str | None = None,
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
    for path, to_rows, latest, archive_name in (
        (rbp, news_rows, "latest_news.json", "rbp.json"),
        (recall, finance_rows, "latest_finance.json", "recall.json"),
        (agentic_rare, agentic_rare_rows, "latest_agentic_rare.json", "agentic_rare.json"),
        (scholar, scholar_rows, "latest_scholar.json", "scholar.json"),
        (legal, legal_rows, "latest_legal.json", "legal.json"),
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
    if findallmcp:
        raw = Path(findallmcp).read_text(encoding="utf-8")
        report = json.loads(raw)
        rows.extend(findallmcp_rows(report, ts))
        write_json(slim_report(report, key="backends"), str(data / "latest_findallmcp.json"))
        (run_dir / "findallmcp.json").write_text(raw, encoding="utf-8")
    for path, archive_name in (
        (fresh, "fresh.jsonl"),
        (gold, "gold.jsonl"),
        (agentic_rare_queries, "agentic_rare.jsonl"),
        (scholar_queries, "scholar.jsonl"),
        (legal_queries, "legal.jsonl"),
        (findallmcp_queries, "findallmcp.jsonl"),
    ):
        if path:
            (run_dir / archive_name).write_bytes(Path(path).read_bytes())

    index_path = data / "runs.json"
    runs = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
    republish = any(r.get("id") == run_id for r in runs)

    _publish_rows(data / "history.jsonl", rows, ts, republish)
    for name, new_rows in (("overlap.jsonl", overlap), ("uniqueness.jsonl", uniqueness)):
        _publish_rows(data / name, new_rows, ts, republish)

    runs = [r for r in runs if r.get("id") != run_id]
    runs.append({"id": run_id, "ts": ts, "artifacts": sorted(p.name for p in run_dir.iterdir())})
    write_json(runs, str(index_path))
    print(f"appended {len(rows)} rows at {ts}; staged {run_id}")


if __name__ == "__main__":
    fire.Fire(publish)
