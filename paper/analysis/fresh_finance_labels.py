import collections
import glob
import gzip
import json
import re
import sys
from unittest.mock import patch

from common import wilson
from finance_runs import gold_queries, gold_rows

from needle.finance.canon import MONEY_REL_TOL
from needle.finance.score import result_answers
from needle.shared.search import DEFAULT_SNIPPET_CHARS, SearchResult, capped_snippet

audit_dir, out_path = sys.argv[1], sys.argv[2]
sample = {s["id"]: s for s in json.load(open(f"{audit_dir}/sample.json"))}
parts = [json.load(open(f)) for f in sorted(glob.glob(f"{audit_dir}/labels_part*.json"))]
labels = {int(row["id"]): row["label"] for rows in parts for row in rows}
missing = sorted(set(sample) - set(labels))
assert not missing, missing[:10]
queries = gold_queries(gold_rows(f"{audit_dir}/queries.jsonl"))
raw = json.load(gzip.open(f"{audit_dir}/raw_out.json.gz", "rt", encoding="utf-8"))
recorded = {(q["query"], e): run["results"] for q in raw["queries"] for e, run in q["by_engine"].items()}
WS = re.compile(r"\s+")


def result(s, **kw):
    return SearchResult(**{**recorded[s["query"], s["engine"]][s["rank"] - 1], **kw})


def answers(s, **kw):
    return result_answers(queries[s["query"]], result(s, **kw), snippet_chars=DEFAULT_SNIPPET_CHARS)


def guideline_answers(s):
    with patch("needle.finance.canon.HEADCOUNT_REL_TOL", MONEY_REL_TOL):
        return answers(s, url="")


def norm(text):
    return WS.sub(" ", text or "").strip()


res = {"labels": {"files": len(parts), "largest_file": max(map(len, parts)), "labels": sum(map(len, parts)), "items": len(labels)}}
for kind in ("money_exact", "other_field"):
    ids = [i for i in sample if sample[i]["kind"] == kind]
    n = len(ids)
    yes = sum(labels[i] == "yes" for i in ids)
    unclear = sum(labels[i] == "unclear" for i in ids)
    lo, hi = wilson(yes, n)
    res[kind] = {"n": n, "yes": yes, "no": n - yes - unclear, "unclear": unclear, "precision": yes / n, "wilson": (lo, hi)}
    print(f"{kind:14s} n {n:3d} yes {yes:3d} unclear {unclear:2d} precision {yes / n:.3f} [{lo:.2f}, {hi:.2f}]")
not_yes, consistent = collections.defaultdict(collections.Counter), collections.Counter()
for i, s in sample.items():
    if s["kind"] == "other_field" and labels[i] != "yes":
        not_yes[s["field"]][labels[i]] += 1
        consistent[s["field"]] += answers(s) and not guideline_answers(s)
other = res["other_field"]
other["consistent"] = other["yes"] + sum(consistent.values())
other["consistent_precision"] = other["consistent"] / other["n"]
res["other_field_not_yes"] = {f: dict(sorted(c.items())) for f, c in sorted(not_yes.items())}
res["other_field_not_yes_consistent"] = {f: c for f, c in sorted(consistent.items()) if c}
print("other_field not yes:", res["other_field_not_yes"])
print(f"other_field consistent with the matcher's rules {other['consistent']}/{other['n']} = {other['consistent_precision']:.3f}",
      res["other_field_not_yes_consistent"])
past, longest = collections.Counter(), 0
for s in sample.values():
    r = result(s)
    seen, matcher = norm(s["snippet"]), norm(capped_snippet(r, DEFAULT_SNIPPET_CHARS))
    assert norm(s["title"]) == norm(r.title) and seen.startswith(matcher), s["id"]
    if len(seen) > len(matcher):
        past[s["kind"]] += 1
        longest = max(longest, len(seen) - len(matcher))
res["graded_text"] = {"covers_matcher_text": len(sample), "past_cutoff": dict(sorted(past.items())), "max_chars_past_cutoff": longest}
print("labels:", res["labels"])
print("graded text:", res["graded_text"])
json.dump(res, open(out_path, "w"), indent=1)
