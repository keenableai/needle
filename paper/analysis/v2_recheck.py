import collections
import json
import os

from needle.finance.canon import MONEY_REL_TOL, _match_amount, gold_in_text
from needle.finance.models import cues_for
from needle.shared.search import SearchResult, titled_snippet

A = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit", "v2hits")
hits = json.load(open(os.path.join(A, "v2hits_all.json")))
labels = {x["id"]: x["verdict"] for p in ("v2labels_part1.json", "v2labels_part2.json") for x in json.load(open(os.path.join(A, p)))}
c = collections.Counter()
for h in hits:
    text = titled_snippet(SearchResult(url=h["url"], title=h["title"], snippet=h["snippet"]), 0)
    if not gold_in_text("money", h["gold_value"], (), text=text, url=h["url"], cues=cues_for(h["field"])):
        kind = "not a hit"
    else:
        kind = "exact" if _match_amount(h["gold_value"], (), text, rel_tol=MONEY_REL_TOL) else "table"
    c[f"{kind} {labels[h['id']]}"] += 1
json.dump(dict(sorted(c.items())), open(os.path.join(A, "recheck.json"), "w"), indent=1)
for k, v in sorted(c.items()):
    print(k, v)
