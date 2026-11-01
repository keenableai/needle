import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
from backfill_scores import rematch_money, rescore  # noqa: E402

from needle.finance.canon import MONEY_REL_TOL, _match_amount  # noqa: E402
from needle.finance.cli import _gold_query  # noqa: E402
from needle.finance.score import result_answers  # noqa: E402
from needle.shared.search import SearchResult, titled_snippet  # noqa: E402


def gold_rows(path):
    return [json.loads(line) for line in open(path) if line.strip()]


def gold_queries(rows):
    return {row["query_text"]: _gold_query(row) for row in rows}


def finance_run(run):
    rep = json.load(open(os.path.join(run, "recall.json")))
    for name, e in rep["engines"].items():
        if "per_query_path" in e:
            rep["engines"][name] = json.load(open(os.path.join(run, e["per_query_path"])))
    rows = gold_rows(os.path.join(run, "gold.jsonl"))
    rematch_money(rep, rows)
    return rescore(rep, "finance"), gold_queries(rows)


def prose_hit(query, r):
    result = SearchResult(url=r["url"], title=r["title"], snippet=r["snippet"])
    return result_answers(query, result, snippet_chars=0) and _match_amount(
        query.value, query.aliases, titled_snippet(result, 0), rel_tol=MONEY_REL_TOL)
