import json
import sys
from collections import Counter, defaultdict

sample_json, sweep_json = sys.argv[1], sys.argv[2]
label_files = sys.argv[3:]
sample = {s["id"]: s for s in json.load(open(sample_json))}
labels = {}
for f in label_files:
    for row in json.load(open(f)):
        labels[row["id"]] = row["label"].strip().lower()
missing = sorted(set(sample) - set(labels))
print("labeled", len(labels), "missing", missing)

yes = Counter()
tot = Counter()
for i, s in sample.items():
    if i not in labels:
        continue
    tot[s["kind"]] += 1
    yes[s["kind"]] += labels[i] == "yes"
for k in sorted(tot):
    print(f"{k:22s} {yes[k]:3d}/{tot[k]:3d} = {yes[k]/tot[k]:.3f}")

kinds = json.load(open(sweep_json))["kinds"]


def weighted(parts):
    n = sum(kinds[k] for k in parts)
    return sum(kinds[k] * yes[k] / tot[k] for k in parts) / n


print("money det precision (weighted)   %.3f" % weighted(["money_exact", "money_banded"]))
print("headcount det precision (weighted) %.3f" % weighted(["numeric_band_exact", "numeric_band_banded"]))
others = [k for k in kinds if k.startswith("other_")]
print("other det precision (weighted)   %.3f" % weighted(others))
allk = [k for k in kinds]
print("all det precision (weighted)     %.3f" % weighted(allk))
no_reasons = [(sample[i]["kind"], sample[i]["gold"], sample[i]["query"]) for i, l in labels.items() if l == "no"]
print("NO items:")
for r in no_reasons:
    print("  ", r)
