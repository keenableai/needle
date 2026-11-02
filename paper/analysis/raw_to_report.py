import asyncio
import gzip
import json
import sys
from types import SimpleNamespace
from unittest.mock import patch

from needle.finance.cli import _gold_ok, _gold_query
from needle.finance.score import run_answers
from needle.shared.cli import load_gold_rows
from needle.shared.io import write_json
from needle.shared.search import DEFAULT_SNIPPET_CHARS, SearchResult
from needle.shared.search.base import SearchRun

queries_path, raw_path, out_path = sys.argv[1:4]
queries = [_gold_query(r) for r in load_gold_rows(queries_path, bench="finance", gold_ok=_gold_ok)]
raw = json.load(gzip.open(raw_path, "rt", encoding="utf-8"))
recorded = {q["query"]: q["by_engine"] for q in raw["queries"]}


async def replay(engines, texts, **_):
    return [[SearchRun(results=[SearchResult(**r) for r in recorded[t][e]["results"]], error=recorded[t][e]["error"],
                       queried_at=recorded[t][e]["queried_at"]) for e in engines] for t in texts]


clients = {e: SimpleNamespace(latencies_ms=[]) for e in raw["engines"]}
with patch("needle.shared.recall.search_all", replay):
    report = asyncio.run(run_answers(queries, clients, num_results=raw["num_results"], snippet_chars=DEFAULT_SNIPPET_CHARS))
write_json(report, out_path, indent=None)
for e, v in report["engines"].items():
    print(f"{e:16s} recall {v['recall_at_k']:.3f} scored {v['num_scored']} errs {v['search_errors']}")
print("wrote", out_path)
