import json
import re
import sys

sw = json.load(open(sys.argv[1]))["sweep"]["money"]
base = sw["0.02"]["per_engine"]
names = sorted(base, key=lambda n: -base[n])
rb = {n: i for i, n in enumerate(names)}
for tol in ("0.0", "0.001", "0.005", "0.01"):
    pe = sw[tol]["per_engine"]
    ranked = sorted(names, key=lambda n: -pe[n])
    r = {n: i for i, n in enumerate(ranked)}
    moves = {n: r[n] - rb[n] for n in names}
    drops = {n: round(base[n] - pe[n], 3) for n in names}
    print(tol, "max|rank move|", max(abs(m) for m in moves.values()), "moves>=2", {n: m for n, m in moves.items() if abs(m) >= 2}, "max recall drop", max(drops.values()), "min", min(drops.values()))

rows = open(sys.argv[2]).read()
tab = []
for line in rows.splitlines():
    cells = [c.strip() for c in line.split("&")]
    if len(cells) < 8 or "ceilbar" in line:
        continue
    name = re.sub(r"\\.*", "", cells[0]).strip()
    try:
        share = float(re.findall(r"\}([\d.]+)\s*$", cells[1])[0]) if "sharebar" in cells[1] else float(cells[1])
    except Exception:
        m = re.search(r"\{(\d+\.?\d*)\}\{", cells[1])
        share = float(m.group(1)) if m else None
    metrics = []
    for c in cells[2:7]:
        m = re.search(r"(\d\.\d+|[01])\s*\}?\s*$", c.replace("}", "} "))
        nums = re.findall(r"\d\.\d+|\b[01]\b", c)
        metrics.append(float(nums[-1]) if nums else None)
    if share is not None and all(v is not None for v in metrics):
        tab.append((name, share, sum(metrics) / 5))
tab.sort(key=lambda t: -t[1])
rank_share = {t[0]: i for i, t in enumerate(tab)}
by_abs = sorted(tab, key=lambda t: -t[2])
rank_abs = {t[0]: i for i, t in enumerate(by_abs)}


def tau_b(a, b):
    n = len(a); c = d = ta = tb = 0
    for i in range(n):
        for j in range(i + 1, n):
            x, y = a[i] - a[j], b[i] - b[j]
            if x == 0 and y == 0:
                continue
            if x == 0:
                ta += 1
            elif y == 0:
                tb += 1
            elif x * y > 0:
                c += 1
            else:
                d += 1
    return (c - d) / (((c + d + ta) * (c + d + tb)) ** 0.5)


print("engines parsed", len(tab))
print("tau_b share vs mean absolute", round(tau_b([t[1] for t in tab], [t[2] for t in tab]), 3))
print("rank moves", {t[0]: rank_abs[t[0]] - rank_share[t[0]] for t in tab if rank_abs[t[0]] != rank_share[t[0]]})
