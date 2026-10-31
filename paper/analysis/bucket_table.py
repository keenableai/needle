import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import NAMES, ULT, bucket_recall, load, window

hist, out = sys.argv[1], sys.argv[2]
rows = load(hist)
w, end = window(rows, 30)
sch = [r for r in w if r["bench"] == "scholar"]
BUCKETS = ["title", "body", "clue", "tot"]
LABELS = {**NAMES, "keenable-realtime": "Keenable realtime", "exa-instant": "Exa Instant", "exa-lite": "Exa Lite",
          "parallel-turbo": "Parallel Turbo", "perplexity-fast": "Perplexity Fast"}


def fmt(x):
    return "1" if round(x, 3) >= 1 else f"{x:.3f}"[1:]


def query_runs(e, b):
    return sum(r[f"{b}_n"] for r in sch
               if r["engine"] == e and r.get(f"{b}_recall") is not None and r.get(f"{b}_n"))


engines = sorted({r["engine"] for r in sch} - {ULT})
rec = {e: {b: bucket_recall(sch, e, b) for b in BUCKETS} for e in engines + [ULT]}
order = sorted(engines, key=lambda e: -rec[e]["title"])
best = {b: max(round(rec[e][b], 3) for e in engines) for b in BUCKETS}

lines = [r"\textit{ceiling (pooled)} & " + " & ".join(rf"\textit{{{fmt(rec[ULT][b])}}}" for b in BUCKETS)
         + rf" & \textit{{{sum(query_runs(ULT, b) for b in BUCKETS):,}}} \\"]
for e in order:
    cells = [rf"\textbf{{{fmt(rec[e][b])}}}" if round(rec[e][b], 3) == best[b] else fmt(rec[e][b]) for b in BUCKETS]
    lines.append(" & ".join([LABELS[e], *cells, f"{sum(query_runs(e, b) for b in BUCKETS):,}"]) + r" \\")
open(out, "w").write("\n".join(lines) + "\n")

ts = sorted({r["ts"] for r in sch})
high = [e for e in engines if rec[e]["title"] >= .71]
low = max((rec[e]["title"], e) for e in engines if e not in high)
body = sorted(((rec[e]["body"], e) for e in engines), reverse=True)
t1 = [(v, e) for v, e in body if e in NAMES]
k = [e for _, e in t1].index("keenable")
print(f"window to {end:%d %b %Y %H:%M}; scholar runs {len(ts)}, first {ts[0]}, last {ts[-1]}; {len(engines)} configurations")
print(f"title >= .71: {len(high)} of {len(engines)}, range {min(rec[e]['title'] for e in high):.3f}-"
      f"{max(rec[e]['title'] for e in high):.3f}; best below: {low[1]} {low[0]:.3f}")
print(f"body keyword range: {body[-1][1]} {body[-1][0]:.3f} to {body[0][1]} {body[0][0]:.3f}")
print("body keyword, Table 1 engines from Keenable:", ", ".join(f"{e} {v:.3f}" for v, e in t1[k:k + 4]))
per_run = [sum(r[f"{b}_n"] for b in BUCKETS) for r in sch if r["engine"] == ULT]
print(f"queries per run {min(per_run)}-{max(per_run)}")
print("query-runs per bucket (ceiling):", {b: query_runs(ULT, b) for b in BUCKETS})
print("query-runs per bucket, min over configurations:",
      {b: min((query_runs(e, b), e) for e in engines) for b in BUCKETS})
print("wrote", out)
