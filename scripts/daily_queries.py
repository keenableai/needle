import json
import os
from pathlib import Path

import fire
import httpx

from keenbench.shared.io import write_jsonl

DEFAULT_DATASET = "keenable-ai/keenbench-results"
OUT = "daily_queries.jsonl"
QUERY_FILES = {"gold.jsonl": "finance", "scholar.jsonl": "scholar", "legal.jsonl": "legal"}
RARE_REPORTS = ("agentic_rare.json", "rarestream.json")


def _dataset(dataset: str | None) -> str:
    return dataset or os.environ.get("HF_DATASET", DEFAULT_DATASET)


def _resolve_base(dataset: str | None) -> str:
    return f"https://huggingface.co/datasets/{_dataset(dataset)}/resolve/main"


def _query_rows(run_id: str, bench: str, text: str) -> list[dict]:
    return [
        {"run_id": run_id, "bench": bench, **json.loads(line)}
        for line in text.splitlines()
        if line.strip()
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
    finance: str | None = None,
    scholar: str | None = None,
    legal: str | None = None,
    agentic_rare: str | None = None,
) -> None:
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        resp = client.get(f"{_resolve_base(dataset)}/{OUT}")
    if resp.status_code == 404:
        rows = []
    else:
        resp.raise_for_status()
        rows = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
    rows = [r for r in rows if r["run_id"] != ts]
    for bench, path in (("finance", finance), ("scholar", scholar), ("legal", legal)):
        if path:
            rows.extend(_query_rows(ts, bench, Path(path).read_text(encoding="utf-8")))
    if agentic_rare:
        rows.extend(_rare_rows(ts, json.loads(Path(agentic_rare).read_text(encoding="utf-8"))))
    _finish(rows, out)


def backfill(out: str = OUT, dataset: str | None = None) -> None:
    api_base = f"https://huggingface.co/api/datasets/{_dataset(dataset)}/tree/main/runs"
    resolve_base = _resolve_base(dataset)
    rows: list[dict] = []
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        url = f"{api_base}?recursive=true&limit=1000"
        paths: list[str] = []
        while url:
            resp = client.get(url)
            resp.raise_for_status()
            paths.extend(f["path"] for f in resp.json() if f["type"] == "file")
            url = resp.links.get("next", {}).get("url")
        rare_by_run: dict[str, str] = {}
        for path in paths:
            run_id, name = path.split("/")[1], path.rsplit("/", 1)[1]
            if name in QUERY_FILES:
                resp = client.get(f"{resolve_base}/{path}")
                resp.raise_for_status()
                rows.extend(_query_rows(run_id, QUERY_FILES[name], resp.text))
            elif name in RARE_REPORTS and run_id not in rare_by_run:
                rare_by_run[run_id] = path
        for run_id, path in rare_by_run.items():
            resp = client.get(f"{resolve_base}/{path}")
            resp.raise_for_status()
            rows.extend(_rare_rows(run_id, resp.json()))
    _finish(rows, out)


if __name__ == "__main__":
    fire.Fire({"update": update, "backfill": backfill})
