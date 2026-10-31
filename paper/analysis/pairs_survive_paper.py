import json

here = __file__.rsplit("/", 1)[0] + "/audit/"
run = json.load(open(here + "adjacent_pairs.json"))
day = json.load(open(here + "adjacent_pairs_day.json"))
mat = json.load(open(here + "matched_pairs_paper.json"))
prod = json.load(open(here + "matched_pairs.json"))
order = run["order"]


def sep(a, b, d, field):
    v = d.get(f"{a}|{b}") or d.get(f"{b}|{a}")
    return bool(v and v.get(field))


def survivors(m):
    return {(a, b) for i, a in enumerate(order) for b in order[i + 1:]
            if sep(a, b, run["all_pairs"], "separated_bonferroni") and sep(a, b, day["all_pairs"], "separated_bonferroni") and sep(a, b, m["pairs"], "sep_bonferroni")}


pairs = [(a, b) for i, a in enumerate(order) for b in order[i + 1:]]
counts = {"run_pointwise": 0, "run_bonferroni": 0, "day_pointwise": 0, "day_bonferroni": 0, "matched_pointwise": 0, "matched_bonferroni": 0, "all_three_pointwise": 0, "all_three_bonferroni": 0}
lost = []
for a, b in pairs:
    rp, rb = sep(a, b, run["all_pairs"], "separated"), sep(a, b, run["all_pairs"], "separated_bonferroni")
    dp, db = sep(a, b, day["all_pairs"], "separated"), sep(a, b, day["all_pairs"], "separated_bonferroni")
    mp, mb = sep(a, b, mat["pairs"], "sep"), sep(a, b, mat["pairs"], "sep_bonferroni")
    counts["run_pointwise"] += rp
    counts["run_bonferroni"] += rb
    counts["day_pointwise"] += dp
    counts["day_bonferroni"] += db
    counts["matched_pointwise"] += mp
    counts["matched_bonferroni"] += mb
    counts["all_three_pointwise"] += rp and dp and mp
    counts["all_three_bonferroni"] += rb and db and mb
    if rb and not (db and mb):
        lost.append((a, b, "day" if not db else "", "matched" if not mb else ""))
new, old = survivors(mat), survivors(prod)
print(counts)
print("Bonferroni pairs separated on the primary estimate but not under day resampling or paper-scorer matched support:", len(lost))
for x in lost:
    print("  ", x)
print("all-three survivors: paper scorer", len(new), "production scorer", len(old))
print("  lost vs production:", sorted(old - new))
print("  gained vs production:", sorted(new - old))
fully = [e for e in order if all(sep(e, f, run["all_pairs"], "separated_bonferroni") and sep(e, f, day["all_pairs"], "separated_bonferroni") and sep(e, f, mat["pairs"], "sep_bonferroni") for f in order if f != e)]
print("separated from every other engine under all three (Bonferroni):", fully)
json.dump({"counts": counts, "lost": lost, "lost_vs_production": sorted(old - new), "gained_vs_production": sorted(new - old), "fully_all_three": fully},
          open(here + "pairs_survive_paper.json", "w"), indent=1)
