import collections
import json
import random
import sys

src, out = sys.argv[1:3]
rows = [json.loads(line) for line in open(src) if line.strip()]
rng = random.Random(1030)
money = [r for r in rows if r["gold"]["field_type"] == "money"]
other = collections.defaultdict(list)
for r in rows:
    if r["gold"]["field_type"] != "money":
        other[r["gold"]["field"]].append(r)
pick = list(money)
for _, rs in sorted(other.items()):
    rng.shuffle(rs)
    pick += rs[: max(10, round(150 * len(rs) / sum(len(v) for v in other.values())))]
rng.shuffle(pick)
with open(out, "w") as f:
    for r in pick:
        f.write(json.dumps(r) + "\n")
print(len(pick), collections.Counter(r["gold"]["field"] for r in pick).most_common())
