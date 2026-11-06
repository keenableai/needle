import collections
import json
import random
import sys
from pathlib import Path

from common import ci

from needle.shared.search.errors import account_side

ENGINES = ["keenable", "keenable-realtime", "kagi", "exa", "chatgpt-search"]
BUCKETS = ["title", "body", "clue", "tot"]


def collect(root):
    rows = []
    for directory in sorted(Path(root).iterdir()):
        if not (directory / "scholar.json").exists():
            continue
        report = json.loads((directory / "scholar.json").read_text())
        if not all(e in report["engines"] for e in ENGINES):
            continue
        queries = {}
        for line in (directory / "scholar.jsonl").read_text().splitlines():
            q = json.loads(line)
            gold = json.loads(q["gold"])
            origin = json.loads(q["query_origin"])
            queries[q["query_text"]] = (gold["paper_key"], origin["bucket"])
        hits = collections.defaultdict(dict)
        for engine in ENGINES:
            path = directory / report["engines"][engine]["per_query_path"]
            for q in json.loads(path.read_text())["per_query"]:
                if q["search_error"] and account_side(q["search_error"]):
                    continue
                paper, bucket = queries[q["query"]]
                hits[paper][engine, bucket] = int(q["hit_rank"] is not None)
        for paper, values in sorted(hits.items()):
            if all((e, b) in values for e in ENGINES for b in BUCKETS):
                rows.append({"run": directory.name, "paper": paper,
                             "hits": [[values[e, b] for b in BUCKETS] for e in ENGINES]})
    return rows


def summarize(rows, samples=2000):
    by_run = collections.defaultdict(list)
    for row in rows:
        by_run[row["run"]].append(row)
    contrasts = {}
    for i, engine in enumerate(ENGINES):
        for j, bucket in enumerate(BUCKETS[1:], 1):
            contrasts[f"{engine}:{bucket}-title"] = (i, j, i, 0)
    for i, engine in enumerate(ENGINES[1:], 1):
        for j, bucket in enumerate(BUCKETS):
            contrasts[f"keenable-{engine}:{bucket}"] = (0, j, i, j)
    runs = list(by_run.values())
    rng = random.Random(1926)
    draws = [[rng.randrange(len(runs)) for _ in runs] for _ in range(samples)]
    result = {}
    for name, (a, b, c, d) in contrasts.items():
        totals = [(sum(r["hits"][a][b] - r["hits"][c][d] for r in run), len(run)) for run in runs]
        mean = sum(s for s, n in totals) / sum(n for s, n in totals)
        estimates = [sum(totals[i][0] for i in draw) / sum(totals[i][1] for i in draw) for draw in draws]
        lo, hi = ci(estimates)
        result[name] = {"mean": mean, "lo": lo, "hi": hi}
    return {"engines": ENGINES, "buckets": BUCKETS, "runs": len(runs), "paper_runs": len(rows),
            "query_runs": len(rows) * len(BUCKETS), "resamples": samples,
            "method": "paired run bootstrap, common papers with all four queries scored by all five configurations; account-side failures excluded; other failures zero; stored identifier hits",
            "dataset_revision": "6a5be09d6d2eed18227b8e1d2c0656bc1c14e5be", "contrasts": result}


if __name__ == "__main__":
    source, out = Path(sys.argv[1]), Path(sys.argv[2])
    if source.is_dir():
        rows = collect(source)
        out.with_suffix(".jsonl").write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))
    else:
        rows = [json.loads(line) for line in source.read_text().splitlines()]
    result = summarize(rows)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
