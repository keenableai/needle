import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import fire
import httpx

from keenbench.shared.hf import dataset_name, resolve_base
from keenbench.shared.io import read_jsonl, write_jsonl

OUT = "daily_queries.jsonl"
WINDOW_HOURS = 24
RUN_ID_FMT = "%Y-%m-%dT%H%MZ"
BENCHES = (
    ("news", "fresh.jsonl", "rbp.json"),
    ("finance", "gold.jsonl", "recall.json"),
    ("agentic_rare", "agentic_rare.jsonl", "agentic_rare.json"),
    ("scholar", "scholar.jsonl", "scholar.json"),
    ("legal", "legal.jsonl", "legal.json"),
)
RARE_REPORTS = ("agentic_rare.json", "rarestream.json")


def _evaluated(report: dict) -> set[str]:
    engine = next(iter(report["engines"].values()))
    return {pq["query"] for pq in engine["per_query"]}


def _bench_rows(run_id: str, bench: str, queries_text: str, report: dict) -> list[dict]:
    evaluated = _evaluated(report)
    rows = read_jsonl(queries_text)
    return [
        {**rec, "run_id": run_id, "bench": bench} for rec in rows if rec["query_text"] in evaluated
    ]


def _rare_rows(run_id: str, report: dict) -> list[dict]:
    engine = next(iter(report["engines"].values()))
    return [
        {"run_id": run_id, "bench": "agentic_rare", "query_text": pq["query"]}
        for pq in engine["per_query"]
    ]


def _finish(rows: list[dict], out: str) -> None:
    rows.sort(key=lambda r: (r["run_id"], r["bench"]))
    write_jsonl(rows, out)
    print(f"wrote {len(rows)} rows to {out}")


def update(
    ts: str,
    out: str = OUT,
    dataset: str | None = None,
    news: str | None = None,
    news_report: str | None = None,
    finance: str | None = None,
    finance_report: str | None = None,
    scholar: str | None = None,
    scholar_report: str | None = None,
    legal: str | None = None,
    legal_report: str | None = None,
    agentic_rare: str | None = None,
    agentic_rare_queries: str | None = None,
) -> None:
    run_id = ts.replace(":", "")
    cutoff = (datetime.strptime(run_id, RUN_ID_FMT) - timedelta(hours=WINDOW_HOURS)).strftime(
        RUN_ID_FMT
    )
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        resp = client.get(f"{resolve_base(dataset)}/{OUT}")
    if resp.status_code == 404:
        rows = []
    else:
        resp.raise_for_status()
        rows = read_jsonl(resp.text)
    rows = [r for r in rows if r["run_id"] != run_id and r["run_id"] >= cutoff]
    paths = {
        "news": (news, news_report),
        "finance": (finance, finance_report),
        "agentic_rare": (agentic_rare_queries, agentic_rare),
        "scholar": (scholar, scholar_report),
        "legal": (legal, legal_report),
    }
    for bench, (queries_path, report_path) in paths.items():
        if queries_path and report_path:
            report = json.loads(Path(report_path).read_text(encoding="utf-8"))
            queries_text = Path(queries_path).read_text(encoding="utf-8")
            rows.extend(_bench_rows(run_id, bench, queries_text, report))
    if agentic_rare and not agentic_rare_queries:
        rows.extend(_rare_rows(run_id, json.loads(Path(agentic_rare).read_text(encoding="utf-8"))))
    _finish(rows, out)


def backfill(out: str = OUT, dataset: str | None = None, hours: int = WINDOW_HOURS) -> None:
    cutoff = (datetime.now(UTC) - timedelta(hours=hours)).strftime(RUN_ID_FMT)
    api_base = f"https://huggingface.co/api/datasets/{dataset_name(dataset)}/tree/main/runs"
    base = resolve_base(dataset)
    rows: list[dict] = []
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:

        def fetch(path: str) -> httpx.Response:
            resp = client.get(f"{base}/{path}")
            resp.raise_for_status()
            return resp

        url: str | None = f"{api_base}?recursive=true&limit=1000"
        by_run: dict[str, set[str]] = {}
        while url:
            resp = client.get(url)
            resp.raise_for_status()
            for f in resp.json():
                if f["type"] != "file":
                    continue
                run_id, name = f["path"].split("/")[1], f["path"].rsplit("/", 1)[1]
                if run_id >= cutoff:
                    by_run.setdefault(run_id, set()).add(name)
            url = resp.links.get("next", {}).get("url")
        for run_id, names in by_run.items():
            for bench, queries_name, report_name in BENCHES:
                if queries_name in names and report_name in names:
                    report = fetch(f"runs/{run_id}/{report_name}").json()
                    queries_text = fetch(f"runs/{run_id}/{queries_name}").text
                    rows.extend(_bench_rows(run_id, bench, queries_text, report))
            if "agentic_rare.jsonl" not in names:
                rare = next((n for n in RARE_REPORTS if n in names), None)
                if rare:
                    rows.extend(_rare_rows(run_id, fetch(f"runs/{run_id}/{rare}").json()))
    _finish(rows, out)


if __name__ == "__main__":
    fire.Fire({"update": update, "backfill": backfill})
