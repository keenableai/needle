import collections
import json
import sys

final_hist, v3_hist, table_tex = sys.argv[1], sys.argv[2], sys.argv[3]
LO, HI = "2026-10-17", "2026-10-30"
FP_STRICT, FP_EXT, FN_MISS = 1 - 130 / 140, 1 - 73 / 80, 10 / 100


def finance_recall(path):
    acc = collections.defaultdict(lambda: [0.0, 0])
    for line in open(path):
        if not line.strip():
            continue
        r = json.loads(line)
        if r["bench"] != "finance" or not (LO <= r["ts"][:10] < HI) or r.get("recall") is None or not r["num_scored"]:
            continue
        acc[r["engine"]][0] += r["recall"] * r["num_scored"]
        acc[r["engine"]][1] += r["num_scored"]
    return {e: s / n for e, (s, n) in acc.items() if n}


before, after = finance_recall(final_hist), finance_recall(v3_hist)
names = [e for e in after if e in before and e != "ultimate"]
rows = []
for e in sorted(names, key=lambda e: -after[e]):
    r = after[e]
    ext = max(0.0, after[e] - before[e])
    fp = FP_STRICT * (r - ext) + FP_EXT * ext
    fn = FN_MISS * (1 - r)
    rows.append((e, r, ext, fp, fn, fn - fp))
    print(f"{e:17s} recall {r:.3f} ext {ext:+.3f} FP {fp:.3f} FN {fn:.3f} net(true-reported) {fn - fp:+.3f}")
nets = [x[5] for x in rows]
print("net range %.3f to %.3f; spread of reported recall %.3f, of corrected %.3f" % (min(nets), max(nets), max(x[1] for x in rows) - min(x[1] for x in rows), max(x[1] + x[5] for x in rows) - min(x[1] + x[5] for x in rows)))
corr = sorted(rows, key=lambda x: -(x[1] + x[5]))
print("order unchanged:", [x[0] for x in corr] == [x[0] for x in rows])
