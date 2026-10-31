import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collections
import random
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import (AXIS, COLORS, FMT, GRID, INK, INK2, MUTED, NAMES, SURFACE, ULT, bootstrap, bucket_recall, load,
                    overall, shares, window)

hist, out = sys.argv[1], sys.argv[2]
rows = load(hist)
w, end = window(rows, 30)
rnd = random.Random(1926)
MARKERS = {"keenable": "o", "exa": "s", "perplexity": "^", "parallel": "D", "google": "v", "chatgpt-search": "P",
           "claude-search": "X", "ultimate": "o"}
FIELD = "#bab9b1"

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["Nimbus Roman", "Times New Roman", "TeX Gyre Termes", "Liberation Serif"],
    "font.size": 7.5, "axes.edgecolor": AXIS, "axes.linewidth": 0.5, "axes.labelcolor": INK2, "xtick.color": INK2,
    "ytick.color": INK2, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "axes.titlesize": 8,
    "axes.titleweight": "bold", "axes.titlecolor": INK, "lines.linewidth": 1.0, "lines.markersize": 3.2,
    "pdf.fonttype": 42,
})


def short(e):
    return NAMES[e].split(" (")[0]


def clean(ax, grid="y"):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0, pad=2)
    if grid:
        ax.grid(axis=grid, color=GRID, lw=0.5)
    ax.set_axisbelow(True)


def label_ends(ax, ends, x, gap, dx, floor):
    ends.sort(key=lambda t: -t[0])
    pos = []
    for y, _label, _color in ends:
        pos.append(min(y, pos[-1] - gap) if pos else y)
    pos[-1] = max(pos[-1], floor)
    for i in range(len(pos) - 2, -1, -1):
        pos[i] = max(pos[i], pos[i + 1] + gap)
    for (y, label, color), p in zip(ends, pos):
        ax.annotate(label, xy=(x, y), xytext=(x + dx, p), fontsize=7.5, color=color, va="center", ha="left",
                    annotation_clip=False,
                    arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.4, shrinkA=0, shrinkB=1)
                    if abs(p - y) > gap * 0.15 else None)


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


def bucket_ci(rs, engine, bucket, n=2000):
    byts = collections.defaultdict(list)
    for r in rs:
        if r["engine"] == engine and r.get(f"{bucket}_recall") is not None and r.get(f"{bucket}_n"):
            byts[r["ts"]].append((r[f"{bucket}_recall"], r[f"{bucket}_n"]))
    runs = list(byts.values())
    vals = []
    for _ in range(n):
        num = den = 0.0
        for _k in range(len(runs)):
            for v, c in runs[rnd.randrange(len(runs))]:
                num += v * c
                den += c
        vals.append(num / den if den else float("nan"))
    return pct(vals, .025), pct(vals, .975)


def series(ax, xs, ys, cis, e):
    c = COLORS[e]
    for x, y, (lo, hi) in zip(xs, ys, cis):
        ax.plot([x, x], [lo, hi], color=c, lw=0.8, alpha=0.6, solid_capstyle="butt", zorder=2)
    ax.plot(xs, ys, "--" if e == ULT else "-", color=c, marker=MARKERS[e], ms=3.2, mec=SURFACE, mew=0.4,
            lw=0.9 if e == ULT else 1.0, zorder=3)


W, H = 6.3, 1.85
fig = plt.figure(figsize=(W, H))
ax1 = fig.add_axes([0.34 / W, 0.4 / H, 2.0 / W, 1.24 / H])
ax2 = fig.add_axes([3.55 / W, 0.4 / H, 1.85 / W, 1.24 / H])

buckets = ["title", "body", "clue", "tot"]
blabels = ["title", "body\nkeyword", "body\nquestion", "tip of\ntongue"]
sch = [r for r in w if r["bench"] == "scholar"]
series_b = ["keenable", "exa", "perplexity", "parallel", "claude-search", "chatgpt-search", "google"]
series_a = [ULT] + series_b
rest = sorted({r["engine"] for r in sch} - set(series_a))
for i, e in enumerate(rest):
    ys = [bucket_recall(sch, e, b) for b in buckets]
    ax1.plot([x + (i % 7 - 3) * 0.035 for x in range(4)], ys, "o", ms=2.2, color=FIELD, mew=0, zorder=1)
ends = []
for j, e in enumerate(series_a):
    ys = [bucket_recall(sch, e, b) for b in buckets]
    xs = [x + (j - 3.5) * 0.035 for x in range(4)]
    series(ax1, xs, ys, [bucket_ci(sch, e, b) for b in buckets], e)
    ends.append((ys[-1], "pooled ceiling" if e == ULT else short(e), MUTED if e == ULT else INK))
label_ends(ax1, ends, 3.1, 0.083, 0.1, 0.05)
ax1.set_xticks(range(4), blabels)
ax1.set_xlim(-0.2, 3.15)
ax1.set_ylim(0, 1.0)
ax1.set_yticks([0, .25, .5, .75, 1], ["0", ".25", ".50", ".75", "1"])
ax1.set_ylabel("recall@10", labelpad=2)
ax1.set_title("a  Scholar recall by query bucket", loc="left", x=-0.12)
clean(ax1)

byweek = collections.defaultdict(list)
for r in rows:
    byweek[datetime.strptime(r["ts"], FMT).strftime("%G-W%V")].append(r)
keys = sorted(byweek)[-9:-1]
wk = {k: shares(byweek[k], series_b)[0] for k in keys}
ci = {k: bootstrap(byweek[k], series_b, n=500, seed=7 + i) for i, k in enumerate(keys)}
ends = []
for i, e in enumerate(series_b):
    pts = [(j + (i - 3) * 0.05, overall(wk[k], e) * 100, [v * 100 for v in ci[k][e]])
           for j, k in enumerate(keys) if overall(wk[k], e) is not None and e in ci[k]]
    xs, ys, cis = zip(*pts)
    series(ax2, xs, ys, cis, e)
    ends.append((ys[-1], short(e), INK))
last = len(keys) - 1
label_ends(ax2, ends, last + 0.15, 3.4, 0.35, 38)
ticks = list(range(1, len(keys), 2))
ax2.set_xticks(ticks, [datetime.strptime(keys[j] + "-1", "%G-W%V-%u").strftime("%-d %b") for j in ticks])
ax2.set_xlim(-0.3, last + 0.2)
ax2.set_ylim(35, 80)
ax2.set_yticks([40, 50, 60, 70, 80])
ax2.set_xlabel("week starting", labelpad=2)
ax2.set_title("b  Weekly overall share, %", loc="left", x=-0.14)
clean(ax2)

fig.savefig(out)

print("wrote", out, "weeks", keys)
