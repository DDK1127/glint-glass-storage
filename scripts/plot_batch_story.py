"""English, high-resolution figure for results/batch-story (run after run_batch_story.py)."""
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/batch-story"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
COLORS = {"no_queue": "#2a78d6", "queue_8": "#eb6834", "queue_8_lru_8": "#1baf7a"}   # validated slots 1-3
LABELS = {"no_queue": "No queue", "queue_8": "Queue, 8 slots", "queue_8_lru_8": "Queue + LRU cache"}
plt.rcParams.update({"font.family": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"], "font.size": 13,
                     "axes.edgecolor": GRID, "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": MUTED,
                     "axes.spines.top": False, "axes.spines.right": False})
SIZE = 2000

agg = {(float(r["overhead_s"]), int(float(r["size"])), r["variant"]): r for r in csv.DictReader(open(OUT / "aggregate.csv"))}
overheads = sorted({k[0] for k in agg})
fig, ax = plt.subplots(figsize=(8, 4.8))
x = np.arange(len(overheads))
w = 0.26
for i, v in enumerate(LABELS):
    vals = [100 * (float(agg[(o, SIZE, v)]["makespan_s"]) / float(agg[(o, SIZE, v)]["lower_bound_s"]) - 1) for o in overheads]
    bars = ax.bar(x + (i - 1) * (w + 0.02), vals, w, color=COLORS[v], label=LABELS[v])
    for b in bars:
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 1, f"{b.get_height():.0f}%", ha="center", fontsize=12, color=INK)
ax.set_xticks(x, [f"{o:g} s per request" for o in overheads])
ax.set_xlabel("Reader time per request (assumption)", color=MUTED)
ax.set_ylabel("Batch completion time above lower bound (%)", color=MUTED)
ax.set_ylim(0, 55)
ax.grid(axis="y", color=GRID, lw=.8)
ax.set_axisbelow(True)
ax.legend(frameon=False, loc="upper right", fontsize=12)
ax.set_title(f"One batch of {SIZE:,} real requests: the queue helps only when reading is fast", loc="left", fontsize=14, color=INK, pad=14)
fig.savefig(OUT / "fig_batch_gap.png", dpi=300, bbox_inches="tight")
print("ok")
