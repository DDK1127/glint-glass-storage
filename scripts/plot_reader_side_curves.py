"""Figures for results/reader-side-curves (run after run_reader_side_curves.py)."""
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/reader-side-curves"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"   # validated categorical slots 1-3
for name in ("PingFang TC", "Heiti TC", "Arial Unicode MS"):
    if any(f.name == name for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = name
        break
plt.rcParams.update({"font.size": 11, "axes.edgecolor": GRID, "axes.labelcolor": INK, "xtick.color": MUTED,
                     "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False})
OVERHEADS = (0.25, 1.0)
TITLE = {0.25: "每個請求讀取開銷 0.25 秒", 1.0: "每個請求讀取開銷 1 秒"}

agg = [dict(r) for r in csv.DictReader(open(OUT / "aggregate.csv"))]
for r in agg:
    for k, v in r.items():
        if k != "variant":
            r[k] = float(v)


def series(o, variant, key):
    sel = sorted((r for r in agg if r["overhead_s"] == o and r["variant"] == variant), key=lambda r: r["rate_req_s"])
    return [r["rate_req_s"] for r in sel], [r[key] for r in sel]


def lines(ax, o, key, spec, scale=1.0):
    ends = []
    for variant, label, color in spec:
        x, y = series(o, variant, key)
        y = [v * scale for v in y]
        ax.plot(x, y, color=color, lw=2, marker="o", ms=6, markeredgecolor="white", markeredgewidth=1.5)
        ends.append([y[-1], label, x[-1]])
    # spread end labels that would collide (LRU and GDS often end at the same value)
    lo, hi = ax.get_ylim()
    gap = (hi - lo) * 0.07
    ends.sort()
    for i in range(1, len(ends)):
        ends[i][0] = max(ends[i][0], ends[i - 1][0] + gap)
    for ypos, label, xpos in ends:
        ax.annotate(label, (xpos, ypos), xytext=(8, 0), textcoords="offset points", va="center", fontsize=10, color=INK, annotation_clip=False)
    ax.grid(axis="y", color=GRID, lw=.8)
    ax.set_xlabel("到達率（每秒請求數）")


# Fig 1: p99 and reader busy vs load, baseline vs LRU vs GDS (C=8)
spec = [("baseline", "沒有 cache", BLUE), ("lru_8", "LRU，8 片", ORANGE), ("gds_8", "GDS，8 片", AQUA)]
fig, axes = plt.subplots(2, 2, figsize=(12, 7.6), gridspec_kw=dict(hspace=.45, wspace=.32))
for j, o in enumerate(OVERHEADS):
    top = max(max(series(o, v, "p99_s")[1]) for v, _, _ in spec)
    axes[0, j].set_ylim(0, top * 1.15)
    lines(axes[0, j], o, "p99_s", spec)
    axes[0, j].set_title(f"{TITLE[o]}：最慢 1% 的等待（秒）", loc="left", fontsize=11, color=INK)
    axes[1, j].set_ylim(40, 108)
    lines(axes[1, j], o, "reader_busy", spec, 100)
    axes[1, j].set_title(f"{TITLE[o]}：Reader 忙碌（%）", loc="left", fontsize=11, color=INK)
for ax in axes.flat:
    ax.set_xlim(right=ax.get_xlim()[1] * 1.22)
fig.savefig(OUT / "fig_cache_vs_load.png", dpi=180, bbox_inches="tight")
plt.close(fig)

# Fig 2: openings vs shuttle fetches (G1), load 0.75
fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), gridspec_kw=dict(wspace=.28))
labels = [("baseline", "沒有 cache"), ("lru_2", "LRU 2 片"), ("lru_8", "LRU 8 片")]
for ax, o in zip(axes, OVERHEADS):
    rows = {r["variant"]: r for r in agg if r["overhead_s"] == o and r["load_mult"] == 0.75}
    x = np.arange(len(labels))
    fetch = [rows[v]["fetch_trips"] for v, _ in labels]
    opens = [rows[v]["opens"] for v, _ in labels]
    b1 = ax.bar(x - .2, fetch, .38, color=BLUE, label="車搬運趟數")
    b2 = ax.bar(x + .2, opens, .38, color=ORANGE, label="玻璃被打開的次數")
    for bars in (b1, b2):
        for b in bars:
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 4, f"{b.get_height():.0f}", ha="center", fontsize=10, color=INK)
    ax.set_xticks(x, [l for _, l in labels])
    ax.set_title(f"{TITLE[o]}（2,000 個請求，負載 0.75）", loc="left", fontsize=11, color=INK)
    ax.grid(axis="y", color=GRID, lw=.8)
    ax.set_ylim(0, max(opens + fetch) * 1.35)
    ax.legend(frameon=False, fontsize=10, loc="upper left", ncol=2)
fig.savefig(OUT / "fig_g1_opens.png", dpi=180, bbox_inches="tight")
plt.close(fig)

# Fig 3: reopen gap CDF (G2), baseline
gaps = {}
for r in csv.DictReader(open(OUT / "reopen_gaps_baseline.csv")):
    gaps.setdefault((float(r["overhead_s"]), float(r["load_mult"])), []).append(float(r["gap_s"]))
fig, ax = plt.subplots(figsize=(8, 4.4))
for (o, m), color, label in (((0.25, 0.75), BLUE, "開銷 0.25 秒"), ((1.0, 0.75), ORANGE, "開銷 1 秒")):
    g = np.sort(np.maximum(gaps[(o, m)], 0.5))
    y = np.arange(1, len(g) + 1) / len(g) * 100
    ax.step(g, y, where="post", color=color, lw=2)
    at30 = (np.asarray(gaps[(o, m)]) <= 30).mean() * 100
    ax.annotate(f"{label}：30 秒內 {at30:.0f}%", (30, at30), xytext=(12, -14 if o == 1.0 else 8), textcoords="offset points", fontsize=10, color=INK)
ax.axvline(30, color=MUTED, lw=1, ls="--")
ax.set_xscale("log")
ax.set_xlabel("同一片玻璃：上次讀完到再次被要求的間隔（秒，對數刻度）")
ax.set_ylabel("累積比例（%）")
ax.set_ylim(0, 100)
ax.grid(color=GRID, lw=.8)
ax.set_title("沒有 cache 時，一片玻璃「再次被打開」距離上次讀完多久（負載 0.75）", loc="left", fontsize=11, color=INK)
fig.savefig(OUT / "fig_g2_reopen_cdf.png", dpi=180, bbox_inches="tight")
plt.close(fig)

# Fig 4: space split (G5), p99 vs load
spec = [("baseline", "buffer 8 / cache 0", BLUE), ("split_6_2", "buffer 6 / cache 2", ORANGE), ("split_4_4", "buffer 4 / cache 4", AQUA)]
fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), gridspec_kw=dict(wspace=.32))
for ax, o in zip(axes, OVERHEADS):
    lines(ax, o, "p99_s", spec)
    ax.set_title(f"{TITLE[o]}：最慢 1% 的等待（秒）", loc="left", fontsize=11, color=INK)
    ax.set_ylim(bottom=0)
    ax.set_xlim(right=ax.get_xlim()[1] * 1.3)
fig.savefig(OUT / "fig_g5_split.png", dpi=180, bbox_inches="tight")
plt.close(fig)
print("ok")
