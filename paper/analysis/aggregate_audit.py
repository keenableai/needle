import json
import os
import sys
from collections import Counter

from common import wilson

audit_dir, out_path = sys.argv[1], sys.argv[2]


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
sweep = load("band_sweep.json")
kinds = sweep["kinds"]


def weighted(parts):
    return sum(kinds[k] * yes[k] / tot[k] for k in parts) / sum(kinds[k] for k in parts)


others = [k for k in kinds if k.startswith("other_")]
other_yes, other_n = sum(yes[k] for k in others), sum(tot[k] for k in others)
lo, hi = wilson(other_yes, other_n)
print(f"other fields {other_yes}/{other_n}  Wilson {lo:.2f}-{hi:.2f}")
matcher = {"money": ["money_exact"], "headcount": ["numeric_band_exact", "numeric_band_banded"], "other": others}
weighted_matcher = {k: weighted(v) for k, v in matcher.items()} | {"all": weighted(sum(matcher.values(), []))}
weighted_wide = {"money": weighted(["money_exact", "money_banded"]), "all": weighted(list(kinds))}
print("weighted precision, matcher:", "  ".join(f"{k} {v:.4f}" for k, v in weighted_matcher.items()))
print("weighted precision, 2% money band:", "  ".join(f"{k} {v:.4f}" for k, v in weighted_wide.items()))
st = sweep["stats"]
up, miss = st["by_type_upgrades"], st["by_type_miss_judged"]
print(f"backstop behind a 2% money band: judged misses {st['det_miss_judged']}, upgraded {st['judge_upgrades']} ({st['judge_upgrades'] / st['det_miss_judged']:.3f})",
      *(f"{ft} {up[ft]}/{miss[ft]} ({up[ft] / miss[ft]:.3f})" for ft in ("money", "exact_id")), sep="; ")
non_money_upgrades = st["judge_upgrades"] - up["money"]
money_hits = round(sweep["sweep"]["money"][str(sweep["reference"]["money"])]["recall"] * st["by_type_queries"]["money"])
min_hits = st["det_hits"] - st["by_type_det_hits"]["money"] + non_money_upgrades + money_hits
print(f"non-money backstop: {non_money_upgrades} upgrades of at least {min_hits} matcher hits (at most {non_money_upgrades / min_hits:.4f})")
json.dump({
    "rechecked": rechecked, "reversed": reversed_,
    "strata": {k: {"yes": yes[k], "n": tot[k], "wilson": wilson(yes[k], tot[k])} for k in sorted(tot)},
    "other_fields": {"yes": other_yes, "n": other_n, "wilson": [lo, hi]},
    "weighted_matcher": weighted_matcher,
    "weighted_money_band_2pct": weighted_wide,
    "backstop_money_band_2pct": {"upgrade_share": st["judge_upgrades"] / st["det_miss_judged"],
                                 **{f"{ft}_upgrade_share": up[ft] / miss[ft] for ft in ("money", "exact_id")}},
    "non_money_backstop": {"upgrades": non_money_upgrades, "min_matcher_hits": min_hits,
                           "max_share": non_money_upgrades / min_hits},
}, open(out_path, "w"), indent=1)
