import json
import os
import sys
from collections import Counter

from common import wilson

audit_dir = sys.argv[1]


def load(path):
    return json.load(open(os.path.join(audit_dir, path)))


def labels(*paths):
    return {int(x["id"]): x["label"].strip().lower() for p in paths for x in load(p)}


strata = [
    (load("sample.json"), labels("labels_part1.json", "labels_part2.json", "labels_part3.json"), labels("exact_more/labels_recheck_orig.json")),
    (load("exact_more/exact_sample.json"), labels("exact_more/labels_part1.json", "exact_more/labels_part2.json"), labels("exact_more/labels_recheck.json")),
]
yes, tot = Counter(), Counter()
for sample, first, recheck in strata:
    for s in sample:
        tot[s["kind"]] += 1
        yes[s["kind"]] += recheck.get(s["id"], first[s["id"]]) == "yes"
rechecked = sum(len(r) for _, _, r in strata)
reversed_ = sum(v == "yes" for _, _, r in strata for v in r.values())
print(f"first-pass rejections rechecked on full text {rechecked}, reversed {reversed_}")
for k in sorted(tot):
    lo, hi = wilson(yes[k], tot[k])
    print(f"{k:22s} {yes[k]:3d}/{tot[k]:3d} = {yes[k] / tot[k]:.3f}  Wilson {lo:.2f}-{hi:.2f}")
kinds = load("band_sweep.json")["kinds"]


def weighted(parts):
    return sum(kinds[k] * yes[k] / tot[k] for k in parts) / sum(kinds[k] for k in parts)


others = [k for k in kinds if k.startswith("other_")]
lo, hi = wilson(sum(yes[k] for k in others), sum(tot[k] for k in others))
print(f"other fields {sum(yes[k] for k in others)}/{sum(tot[k] for k in others)}  Wilson {lo:.2f}-{hi:.2f}")
print(f"weighted precision: money {weighted(['money_exact', 'money_banded']):.3f}  headcount {weighted(['numeric_band_exact', 'numeric_band_banded']):.3f}  other {weighted(others):.3f}  all {weighted(list(kinds)):.3f}")
