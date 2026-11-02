import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from needle.finance.projection import QUOTED_SPAN_RE as FINANCE_QUOTE
from needle.legal.projection import QUOTED_SPAN_RE as LEGAL_QUOTE
from needle.shared.search.queryops import parse_ops

BENCHES = {"finance": ("recall.json", "gold.jsonl", FINANCE_QUOTE), "legal": ("legal.json", "legal.jsonl", LEGAL_QUOTE)}


def group(bench, row):
    if bench == "legal":
        return json.loads(row["query_origin"])["bucket"]
    return "filing" if row["gold"]["field"] == "filing" else row["gold"]["field_type"]


def count(bench, runs_dir):
    report, queries, quote = BENCHES[bench]
    runs = sorted(p for p in Path(runs_dir).iterdir() if (p / report).exists())
    groups = defaultdict(Counter)
    for run in runs:
        rows = {}
        for line in open(run / queries):
            if line.strip():
                row = json.loads(line)
                rows[row["query_text"]] = row
        asked = set()
        for e in json.load(open(run / report))["engines"].values():
            p = run / e.get("per_query_path", "")
            if p.is_file():
                asked |= {q["query"] for q in json.load(open(p))["per_query"]}
        for q in sorted(asked):
            row = rows[q]
            ops = parse_ops(q)
            has_op = bool(ops.sites or ops.after or ops.before)
            has_quote = bool(quote.search(q))
            c = groups[group(bench, row)]
            c["query_runs"] += 1
            c["operator_or_quote"] += has_op or has_quote
            c["operator"] += has_op
            c["quote"] += has_quote
            c[f"syntax_{json.loads(row['query_origin']).get('syntax', 'plain')}"] += 1
    return {"runs": [r.name for r in runs], "groups": {g: dict(sorted(c.items())) for g, c in sorted(groups.items())}}


finance_dir, legal_dir, out_json = sys.argv[1:4]
out = {"finance": count("finance", finance_dir), "legal": count("legal", legal_dir)}
json.dump(out, open(out_json, "w"), indent=1)
for bench, v in out.items():
    print(bench, len(v["runs"]), "runs")
    for g, c in v["groups"].items():
        print(f"  {g:14s} {c['operator_or_quote']:4d} of {c['query_runs']:4d} with an operator or quote ({c['quote']} quote)")
