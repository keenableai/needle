import collections
import json
import random

D = "/tmp/claude-1000/-home-yallen-needle/c4aada69-467d-4c90-a8ab-6f8f7f7f5851/scratchpad/fresh/"
rows = [json.loads(l) for l in open(D + "finance_q.jsonl") if l.strip()]
rng = random.Random(1030)
money = [r for r in rows if r["gold"]["field_type"] == "money"]
other = collections.defaultdict(list)
for r in rows:
    if r["gold"]["field_type"] != "money":
        other[r["gold"]["field"]].append(r)
pick = list(money)
for field, rs in sorted(other.items()):
    rng.shuffle(rs)
    pick += rs[: max(10, round(150 * len(rs) / sum(len(v) for v in other.values())))]
rng.shuffle(pick)
with open(D + "fresh_subset.jsonl", "w") as f:
    for r in pick:
        f.write(json.dumps(r) + "\n")
print(len(pick), collections.Counter(r["gold"]["field"] for r in pick).most_common())
