import json
import time
from pathlib import Path

import fire
import httpx
from huggingface_hub import get_token
from publish_bench import finance_rows, legal_rows, scholar_rows

from needle.finance.cli import _gold_query
from needle.finance.score import _summary as finance_summary
from needle.finance.score import _ultimate as finance_ultimate
from needle.finance.score import result_answers
from needle.legal.score import _summary as legal_summary
from needle.scholar.score import _summary as scholar_summary
from needle.shared.ci import ci_payload, score_row
from needle.shared.hf import fetch_report, resolve_base
from needle.shared.io import load_jsonl, write_json, write_jsonl
from needle.shared.recall import ULTIMATE, first_rank, summarize_engines, ultimate_per_query
from needle.shared.retry import RETRYABLE_STATUSES
from needle.shared.search import SearchResult

BENCHES = {
    "finance": ("recall.json", finance_summary, finance_ultimate, finance_rows),
    "scholar": ("scholar.json", scholar_summary, ultimate_per_query, scholar_rows),
    "legal": ("legal.json", legal_summary, ultimate_per_query, legal_rows),
}
LATENCY_KEYS = frozenset({"p50_ms", "p95_ms", "lat_ms"})


def rematch_money(report: dict, gold_rows: list[dict]) -> None:
    gold = {row["query_text"]: _gold_query(row) for row in gold_rows}
    for name, e in report["engines"].items():
        if name == ULTIMATE:
            continue
        for pq in e["per_query"]:
            query = gold[pq["query"]]
            if pq["search_error"] is not None or query.field_type != "money":
                continue
            matches = [
                result_answers(
                    query,
                    SearchResult(url=r["url"], title=r["title"], snippet=r["snippet"]),
                    snippet_chars=0,
                )
                for r in pq["results"]
            ]
            pq["det_rank"] = pq["hit_rank"] = first_rank(matches)
            pq["judged"] = pq["judge_errors"] = 0
            for r, m in zip(pq["results"], matches, strict=True):
                r["det_match"], r["judge_match"] = m, None


def rescore(report: dict, bench: str) -> dict:
    _, summary, ultimate_fn, _ = BENCHES[bench]
    engines = {n: e for n, e in report["engines"].items() if n != ULTIMATE}
    query_outs = [
        list(entries) for entries in zip(*(e["per_query"] for e in engines.values()), strict=True)
    ]
    return {
        **report,
        "engines": summarize_engines(
            query_outs,
            {n: e.get("latency") for n, e in engines.items()},
            summary,
            ultimate_fn,
            cap=report["num_results"],
        ),
    }


def _get_report(client: httpx.Client, runs_base: str, run_id: str, artifact: str) -> dict:
    for attempt in range(7):
        try:
            return fetch_report(client, runs_base, run_id, artifact)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in RETRYABLE_STATUSES:
                raise
            time.sleep(min(5 * 2**attempt, 300))
    return fetch_report(client, runs_base, run_id, artifact)


def _get_jsonl(client: httpx.Client, url: str) -> list[dict]:
    resp = client.get(url)
    resp.raise_for_status()
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def backfill(site: str, dataset: str | None = None) -> None:
    data = Path(site) / "data"
    history = load_jsonl(data / "history.jsonl")
    scores = load_jsonl(data / "ci_scores.jsonl")
    runs = json.loads((data / "runs.json").read_text(encoding="utf-8"))
    runs_base = f"{resolve_base(dataset)}/runs"
    rows_by_key = {(r["ts"], r["bench"], r["engine"]): r for r in history}
    score_ts = {(r["ts"], r["bench"]) for r in scores}
    in_history = {(r["ts"], r["bench"]) for r in history}
    new_scores: dict[tuple[str, str], dict] = {}
    n_rows = n_runs = 0
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(timeout=120.0, follow_redirects=True, headers=headers) as client:
        for run in runs:
            for bench, (artifact, _, _, to_rows) in BENCHES.items():
                if artifact not in run["artifacts"] or (run["ts"], bench) not in in_history:
                    continue
                report = _get_report(client, runs_base, run["id"], artifact)
                if bench == "finance":
                    gold_rows = _get_jsonl(client, f"{runs_base}/{run['id']}/gold.jsonl")
                    rematch_money(report, gold_rows)
                report = rescore(report, bench)
                n_runs += 1
                for new in to_rows(report, run["ts"]):
                    row = rows_by_key.get((run["ts"], bench, new["engine"]))
                    if row is None:
                        continue
                    row.update({k: v for k, v in new.items() if k not in LATENCY_KEYS})
                    n_rows += 1
                if (run["ts"], bench) in score_ts:
                    new_scores[(run["ts"], bench)] = score_row(report, bench, run["ts"])
                print(f"{run['ts']} {bench}", flush=True)
    write_jsonl(history, str(data / "history.jsonl"))
    if new_scores:
        scores = [new_scores.get((r["ts"], r["bench"]), r) for r in scores]
        write_jsonl(scores, str(data / "ci_scores.jsonl"))
        write_json(ci_payload(scores, max(r["ts"] for r in scores)), str(data / "ci.json"))
    print(f"rescored {n_rows} rows across {n_runs} runs; {len(new_scores)} ci score rows")


if __name__ == "__main__":
    fire.Fire(backfill)
