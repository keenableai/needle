import collections
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import ACCOUNT_SIDE_FAILURES, BENCHES, load

hist, pairs = sys.argv[1], sys.argv[2]
runs = set(json.load(open(pairs))["runs"])
acc = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
for line in open(hist):
    r = json.loads(line)
    if r["ts"] not in runs or r["bench"] not in dict(BENCHES) or r["engine"] not in ACCOUNT_SIDE_FAILURES:
        continue
    acc[r["engine"]][r["bench"]][0] += r.get("search_errors") or 0
    acc[r["engine"]][r["bench"]][1] += r.get("num_queries") or 0
for e in sorted(acc):
    tot_e = sum(v[0] for v in acc[e].values())
    tot_n = sum(v[1] for v in acc[e].values())
    per = {b: f"{v[0]}/{v[1]}" for b, v in acc[e].items()}
    print(f"{e:17s} excluded {tot_e}/{tot_n} = {100 * tot_e / tot_n:.1f}%  {per}")
