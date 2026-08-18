from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from keenbench.shared.identity import query_hash
from keenbench.shared.overlap import TS_FMT

WINDOW_DAYS = 7
RESAMPLES = 10000
CONFIDENCE = 0.95
METHOD = "percentile cluster bootstrap, wider of query and run clustering"
CHUNK_CELLS = 250_000
SEED = 0


def score_row(report: dict, bench: str, ts: str) -> dict:
    qids: list[str] = []
    engines = {}
    for name, e in report["engines"].items():
        pqs = e["per_query"]
        if not qids:
            qids = [query_hash(pq["query"]) for pq in pqs]
        engines[name] = [None if pq["score"] is None else round(pq["score"], 4) for pq in pqs]
    return {"ts": ts, "bench": bench, "qids": qids, "engines": engines}


def updated_scores(existing: list[dict], new_rows: list[dict], ts: str) -> list[dict]:
    rows = [r for r in existing if r["ts"] != ts] + new_rows
    if not rows:
        return []
    end = datetime.strptime(max(r["ts"] for r in rows), TS_FMT)
    cutoff = (end - timedelta(days=WINDOW_DAYS)).strftime(TS_FMT)
    return [r for r in rows if r["ts"] > cutoff]


def bootstrap_interval(clusters: dict[str, list[float]], resamples: int) -> tuple[float, float]:
    rng = np.random.default_rng(SEED)
    sums = np.array([sum(v) for v in clusters.values()])
    counts = np.array([len(v) for v in clusters.values()], dtype=float)
    size = len(sums)
    stats = np.empty(resamples)
    chunk = max(1, CHUNK_CELLS // size)
    for start in range(0, resamples, chunk):
        idx = rng.integers(0, size, size=(min(chunk, resamples - start), size))
        stats[start : start + len(idx)] = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    alpha = (1 - CONFIDENCE) / 2
    lo, hi = np.quantile(stats, [alpha, 1 - alpha])
    return float(lo), float(hi)


def ci_payload(rows: list[dict], window_end: str, *, resamples: int = RESAMPLES) -> dict[str, Any]:
    benches: dict[str, Any] = {}
    runs: dict[str, list[str]] = {}
    for bench in sorted({r["bench"] for r in rows}):
        bench_rows = [r for r in rows if r["bench"] == bench]
        engines: dict[str, Any] = {}
        for name in sorted({n for r in bench_rows for n in r["engines"]}):
            by_query: dict[str, list[float]] = defaultdict(list)
            by_run: dict[str, list[float]] = defaultdict(list)
            for r in bench_rows:
                scores = r["engines"].get(name)
                if not scores:
                    continue
                for qid, s in zip(r["qids"], scores, strict=True):
                    if s is not None:
                        by_query[qid].append(s)
                        by_run[r["ts"]].append(s)
            intervals = [
                bootstrap_interval(clusters, resamples)
                for clusters in (by_query, by_run)
                if len(clusters) >= 2
            ]
            if not intervals:
                continue
            scored = [s for v in by_query.values() for s in v]
            engines[name] = {
                "point": round(sum(scored) / len(scored), 4),
                "lo": round(min(lo for lo, _ in intervals), 4),
                "hi": round(max(hi for _, hi in intervals), 4),
            }
        if engines:
            benches[bench] = engines
            runs[bench] = sorted({r["ts"] for r in bench_rows})
    return {
        "confidence": CONFIDENCE,
        "resamples": resamples,
        "window_days": WINDOW_DAYS,
        "window_end": window_end,
        "method": METHOD,
        "runs": runs,
        "benches": benches,
    }
