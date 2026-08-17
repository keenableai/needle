import hashlib
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from keenbench.shared.overlap import TS_FMT

NDCG_BENCHES = ("news", "agentic_rare")
WINDOW_DAYS = 7
RESAMPLES = 10000
CONFIDENCE = 0.95
METHOD = "percentile cluster bootstrap, wider of query and run clustering"
CHUNK_CELLS = 2_000_000


def parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, TS_FMT)


def query_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def per_query_score(bench: str, pq: dict) -> float | None:
    if bench in NDCG_BENCHES:
        ndcg = pq.get("ndcg")
        return None if ndcg is None else round(float(ndcg), 4)
    if pq["search_error"] is not None:
        return None
    if bench == "finance" and pq.get("judge_errors") and pq.get("hit_rank") is None:
        return None
    return 1.0 if pq.get("hit_rank") is not None else 0.0


def score_row(report: dict, bench: str, ts: str) -> dict:
    qids: list[str] = []
    engines = {}
    for name, e in report["engines"].items():
        pqs = e["per_query"]
        if not qids:
            qids = [query_id(pq["query"]) for pq in pqs]
        engines[name] = [per_query_score(bench, pq) for pq in pqs]
    return {"ts": ts, "bench": bench, "qids": qids, "engines": engines}


def updated_scores(
    existing: list[dict], new_rows: list[dict], ts: str, window_days: int = WINDOW_DAYS
) -> list[dict]:
    rows = [r for r in existing if r["ts"] != ts] + new_rows
    if not rows:
        return []
    cutoff = parse_ts(max(r["ts"] for r in rows)) - timedelta(days=window_days)
    return [r for r in rows if parse_ts(r["ts"]) > cutoff]


def bootstrap_interval(
    clusters: dict[str, tuple[float, int]],
    rng: np.random.Generator,
    resamples: int,
    confidence: float,
) -> tuple[float, float]:
    sums = np.array([s for s, _ in clusters.values()])
    counts = np.array([n for _, n in clusters.values()], dtype=float)
    size = len(sums)
    stats = np.empty(resamples)
    chunk = max(1, CHUNK_CELLS // size)
    for start in range(0, resamples, chunk):
        idx = rng.integers(0, size, size=(min(chunk, resamples - start), size))
        stats[start : start + len(idx)] = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    alpha = (1 - confidence) / 2
    return float(np.quantile(stats, alpha)), float(np.quantile(stats, 1 - alpha))


def ci_payload(
    rows: list[dict],
    window_end: str,
    *,
    window_days: int = WINDOW_DAYS,
    resamples: int = RESAMPLES,
    confidence: float = CONFIDENCE,
) -> dict[str, Any]:
    rng = np.random.default_rng(int.from_bytes(hashlib.sha1(window_end.encode()).digest()[:8]))
    end = parse_ts(window_end)
    cutoff = end - timedelta(days=window_days)
    rows = [r for r in rows if cutoff < parse_ts(r["ts"]) <= end]
    benches: dict[str, Any] = {}
    for bench in sorted({r["bench"] for r in rows}):
        bench_rows = [r for r in rows if r["bench"] == bench]
        engines: dict[str, Any] = {}
        for name in sorted({n for r in bench_rows for n in r["engines"]}):
            by_query: dict[str, tuple[float, int]] = {}
            by_run: dict[str, tuple[float, int]] = {}
            total, count = 0.0, 0
            for r in bench_rows:
                scores = r["engines"].get(name)
                if not scores:
                    continue
                for qid, s in zip(r["qids"], scores, strict=True):
                    if s is None:
                        continue
                    for key, acc in ((qid, by_query), (r["ts"], by_run)):
                        prev = acc.get(key, (0.0, 0))
                        acc[key] = (prev[0] + s, prev[1] + 1)
                    total += s
                    count += 1
            intervals = [
                bootstrap_interval(clusters, rng, resamples, confidence)
                for clusters in (by_query, by_run)
                if len(clusters) >= 2
            ]
            if not count or not intervals:
                continue
            engines[name] = {
                "point": round(total / count, 4),
                "lo": round(min(lo for lo, _ in intervals), 4),
                "hi": round(max(hi for _, hi in intervals), 4),
            }
        if engines:
            benches[bench] = {"method": METHOD, "engines": engines}
    return {
        "confidence": confidence,
        "resamples": resamples,
        "window_days": window_days,
        "window_end": window_end,
        "benches": benches,
    }
