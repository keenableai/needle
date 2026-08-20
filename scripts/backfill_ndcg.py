import json
from pathlib import Path

import fire
import httpx

from needle.shared.hf import resolve_base
from needle.shared.io import load_jsonl, write_jsonl
from needle.shared.metrics import dcg_at_k, normalize_url

ARTIFACTS = {
    "news": ("ndcg.json", "rbp.json"),
    "agentic_rare": ("agentic_rare.json", "rarestream.json"),
}
LEGACY_BENCH = {"freshstream": "news", "rarestream": "agentic_rare"}


def _pooled_idcg(report: dict, query: str, k: int) -> float | None:
    best: dict[str, int] = {}
    for e in report["engines"].values():
        for pq in e["per_query"]:
            if pq["query"] != query or pq["search_error"] is not None:
                continue
            for r in pq["results"]:
                rating = r.get("rating")
                if rating is None:
                    continue
                norm = normalize_url(r["url"])
                if norm not in best or rating > best[norm]:
                    best[norm] = rating
    if not best:
        return None
    return dcg_at_k(sorted(best.values(), reverse=True), k=k) or None


def report_ndcg(report: dict) -> dict[str, float]:
    engines = report["engines"]
    sample = next(iter(engines.values()), None)
    if sample is None:
        return {}
    if "mean_ndcg" in sample:
        return {name: e["mean_ndcg"] for name, e in engines.items()}
    k = report.get("k") or report.get("num_results") or 5
    ultimate = engines.get("ultimate")
    if ultimate is not None:
        idcgs = {
            pq["query"]: dcg_at_k(pq["penalized_ratings"], k=k) or None
            for pq in ultimate["per_query"]
            if pq["rbp"] is not None
        }
    else:
        queries = {pq["query"] for e in engines.values() for pq in e["per_query"]}
        idcgs = {q: _pooled_idcg(report, q, k) for q in queries}
    out = {}
    for name, e in engines.items():
        scored = []
        for pq in e["per_query"]:
            idcg = idcgs.get(pq["query"])
            if pq["rbp"] is None or not idcg:
                continue
            scored.append(dcg_at_k(pq["penalized_ratings"], k=k) / idcg)
        out[name] = sum(scored) / len(scored) if scored else 0.0
    out.setdefault("ultimate", 1.0 if any(idcgs.values()) else 0.0)
    return out


def backfill(site: str, dataset: str | None = None) -> None:
    data = Path(site) / "data"
    history = load_jsonl(data / "history.jsonl")
    runs = json.loads((data / "runs.json").read_text(encoding="utf-8"))
    runs_base = f"{resolve_base(dataset)}/runs"
    by_key: dict[tuple[str, str], list[dict]] = {}
    for row in history:
        bench = LEGACY_BENCH.get(row["bench"], row["bench"])
        by_key.setdefault((row["ts"], bench), []).append(row)
    n_rows = 0
    n_runs = 0
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        for run in runs:
            for bench, names in ARTIFACTS.items():
                rows = by_key.get((run["ts"], bench))
                if not rows or all("ndcg" in r for r in rows):
                    continue
                artifact = next((a for a in names if a in run["artifacts"]), None)
                if artifact is None:
                    continue
                resp = client.get(f"{runs_base}/{run['id']}/{artifact}")
                resp.raise_for_status()
                means = report_ndcg(resp.json())
                n_runs += 1
                for row in rows:
                    if "ndcg" in row or row["engine"] not in means:
                        continue
                    row["ndcg"] = means[row["engine"]]
                    n_rows += 1
    write_jsonl(history, str(data / "history.jsonl"))
    print(f"added ndcg to {n_rows} rows across {n_runs} runs")


if __name__ == "__main__":
    fire.Fire(backfill)
