import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collections
import json
import random
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

from common import (AXIS, BLUES, COLORS, FAMILIES, FMT, GRID, INK, INK2, MUTED, NAMES, SURFACE, ULT, bootstrap,
                    bucket_recall, load, overall, shares, window)

hist, indep, out = sys.argv[1], sys.argv[2], sys.argv[3]
rows = load(hist)
w, end = window(rows, 30)
rnd = random.Random(1926)
MARKERS = {"keenable": "o", "exa": "s", "perplexity": "^", "parallel": "D", "google": "v", "chatgpt-search": "P",
           "claude-search": "X", "ultimate": "o"}

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


def label_ends(ax, ends, x, gap, dx=0.1, size=7.5):
    ends.sort(key=lambda t: -t[0])
    pos = []
    for y, label, color in ends:
        p = y
        if pos and pos[-1] - p < gap:
            p = pos[-1] - gap
        pos.append(p)
        ax.annotate(label, xy=(x, y), xytext=(x + dx, p), fontsize=size, color=color, va="center", ha="left",
                    annotation_clip=False,
                    arrowprops=dict(arrowstyle="-", color=AXIS, lw=0.5, shrinkA=0, shrinkB=1) if abs(p - y) > 0.012 else None)


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


fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6.3, 1.85), gridspec_kw={"width_ratios": [1.0, 1.0]})

buckets = ["title", "body", "clue", "tot"]
blabels = ["title", "body\nkeyword", "body\nquestion", "tip of\ntongue"]
sch = [r for r in w if r["bench"] == "scholar"]
series_a = ["ultimate", "keenable", "perplexity", "exa", "google", "chatgpt-search"]
ends = []
for j, e in enumerate(series_a):
    ys = [bucket_recall(sch, e, b) for b in buckets]
    cis = [bucket_ci(sch, e, b) for b in buckets]
    xs = [x + (j - 2.5) * 0.025 for x in range(4)]
    c = COLORS[e]
    for x, y, (lo, hi) in zip(xs, ys, cis):
        ax1.plot([x, x], [lo, hi], color=c, lw=0.7, alpha=0.55, solid_capstyle="butt", zorder=2)
    ax1.plot(xs, ys, "--" if e == ULT else "-", color=c, marker=MARKERS.get(e, "o"), ms=3.2, mec=SURFACE, mew=0.4,
             lw=1.0 if e != ULT else 0.9, zorder=3)
    ends.append((ys[-1], "pooled ceiling" if e == ULT else short(e), INK if e != ULT else MUTED))
label_ends(ax1, ends, 3.06, 0.085, dx=0.08)
ax1.set_xticks(range(4), blabels)
ax1.set_xlim(-0.15, 3.1)
ax1.set_ylim(0, 1.0)
ax1.set_yticks([0, .25, .5, .75, 1], ["0", ".25", ".50", ".75", "1"])
ax1.set_ylabel("recall@10", labelpad=2)
ax1.set_title("a  Scholar recall by query bucket", loc="left", x=-0.1)
clean(ax1)

series = ["keenable", "exa", "perplexity", "parallel", "google", "chatgpt-search", "claude-search"]
byweek = collections.defaultdict(list)
for r in rows:
    byweek[datetime.strptime(r["ts"], FMT).strftime("%G-W%V")].append(r)
keys = sorted(byweek)[-9:-1]
wk = {k: shares(byweek[k], series)[0] for k in keys}
ci = {k: bootstrap(byweek[k], series, n=500, seed=7 + i) for i, k in enumerate(keys)}
sh_w, _ = shares(w, series)
order_b = sorted(series, key=lambda e: -(overall(sh_w, e) or 0))
greys = [LinearSegmentedColormap.from_list("g", ["#c6c5bd", "#141414"])(t) for t in np.linspace(0, 1, len(keys))]
spread = 0.085
for i, e in enumerate(order_b):
    for j, k in enumerate(keys):
        v = overall(wk[k], e)
        if v is None or e not in ci[k]:
            continue
        y = i + (j - (len(keys) - 1) / 2) * spread
        lo, hi = ci[k][e]
        ax2.plot([lo * 100, hi * 100], [y, y], color=greys[j], lw=0.6, alpha=0.5, solid_capstyle="butt", zorder=2)
        ax2.plot(v * 100, y, "o", ms=2.9, color=greys[j], mec=SURFACE, mew=0.3, zorder=3)
ax2.set_yticks(range(len(order_b)), [short(e) for e in order_b])
ax2.set_ylim(len(order_b) - 0.5, -0.5)
ax2.set_xlim(34, 80)
ax2.set_xticks([40, 50, 60, 70, 80], ["40", "50", "60", "70", "80%"])
ax2.set_xlabel("share of pooled ceiling, per ISO week", labelpad=2)
ax2.set_title("b  Weekly leaderboard, eight weeks", loc="left", x=-0.42)
clean(ax2, grid="x")
ax2.spines["left"].set_visible(False)
lx0, ly = 37.5, -0.3
for j, k in enumerate(keys):
    ax2.plot(lx0 + j * 1.3, ly, "o", ms=2.9, color=greys[j], mec=SURFACE, mew=0.3, clip_on=False)
ax2.text(lx0 + (len(keys) - 1) * 1.3 + 1.2, ly, f"ISO week {keys[0].split('-W')[1]} to {keys[-1].split('-W')[1]}",
         ha="left", va="center", fontsize=7, color=INK2, bbox=dict(facecolor=SURFACE, edgecolor="none", pad=1.0))

fig.subplots_adjust(left=0.075, right=0.985, top=0.89, bottom=0.215, wspace=0.62)
fig.savefig(out)

fig2, ax3 = plt.subplots(figsize=(3.9, 3.75))
ind = json.load(open(indep))["all"]["overlap"]
engines = sorted({r["engine"] for r in w} - {ULT})
sh, _ = shares(w, engines)
base = [e for e in engines if e not in FAMILIES]
order = sorted(base, key=lambda e: -(overall(sh, e) or 0))
if len(sys.argv) > 4:
    table_order = json.load(open(sys.argv[4]))["order"]
    order = [e for e in table_order if e in base] + [e for e in order if e not in table_order]
idx = {e: i for i, e in enumerate(order)}
n = len(order)
mat = [[float("nan")] * n for _ in range(n)]
for x in ind:
    if x["a"] in idx and x["b"] in idx and x["union_urls"]:
        j = x["shared_urls"] / x["union_urls"]
        i, k = idx[x["a"]], idx[x["b"]]
        mat[max(i, k)][min(i, k)] = j
cmap = LinearSegmentedColormap.from_list("blues", BLUES[1:], N=64)
cmap.set_bad("#ffffff")
m = np.array(mat)
im = ax3.imshow(m, cmap=cmap, vmin=0, vmax=0.65, aspect="equal")
ax3.set_xticks(np.arange(-0.5, n, 1), minor=True)
ax3.set_yticks(np.arange(-0.5, n, 1), minor=True)
ax3.grid(which="minor", color="#ffffff", lw=0.6)
ax3.tick_params(which="minor", length=0)
labels = [short(e).replace("ChatGPT search", "ChatGPT").replace("Claude search", "Claude").replace("You.com", "You")
          for e in order]
ax3.set_xticks(range(n), labels, fontsize=7.5, rotation=90)
ax3.set_yticks(range(n), labels, fontsize=7.5)
ax3.tick_params(which="major", length=0, pad=1.5)
for s in ax3.spines.values():
    s.set_visible(False)
for i in range(n):
    for k in range(i):
        if m[i][k] >= 0.15:
            ax3.text(k, i, f"{round(m[i][k] * 100):02d}", ha="center", va="center", fontsize=7,
                     color="#ffffff" if m[i][k] > 0.42 else INK)
cax = ax3.inset_axes([0.52, 0.86, 0.36, 0.035])
cb = fig2.colorbar(im, cax=cax, orientation="horizontal", ticks=[0, .2, .4, .6])
cb.ax.tick_params(labelsize=7, length=0, pad=1.5)
cb.outline.set_visible(False)
cb.ax.set_title("Jaccard overlap of returned URLs", fontsize=7.5, color=INK2, pad=3, loc="left", fontweight="normal")

fig2.subplots_adjust(left=0.2, right=0.995, top=0.995, bottom=0.17)
fig2.savefig(out.replace("results", "overlap"))
print("wrote", out, "weeks", keys)
