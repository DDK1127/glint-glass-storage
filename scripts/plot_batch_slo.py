"""English, high-resolution figure for results/batch-slo (run after run_batch_slo.py)."""
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/batch-slo"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE = "#2a78d6", "#eb6834"
plt.rcParams.update({"font.family": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"], "font.size": 13,
                     "axes.edgecolor": GRID, "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": MUTED,
                     "axes.spines.top": False, "axes.spines.right": False})
rows = [r for r in csv.DictReader(open(OUT / "aggregate.csv")) if r["variant"] == "queue_8"]
fig, ax = plt.subplots(figsize=(8, 4.8))
for mbs, color in (("30", BLUE), ("210", ORANGE)):
    sel = sorted((r for r in rows if r["read_mb_s"] == mbs), key=lambda r: float(r["interval_s"]))
    x = [float(r["size"]) for r in sel]
    p99 = [float(r["p99_s"]) / 60 for r in sel]
    lb = [float(r["lower_bound_s"]) / 60 for r in sel]
    ax.plot(x, p99, color=color, lw=2.2, marker="o", ms=7, markeredgecolor="white", markeredgewidth=1.5)
    ax.plot(x, lb, color=color, lw=1.2, ls="--")
    ax.annotate(f"Reader {mbs} MB/s", (x[-1], p99[-1]), xytext=(8, 0), textcoords="offset points", va="center", fontsize=12, color=INK)
ax.set_xscale("log")
ax.set_xticks([1206, 2371, 4326, 13380, 33364], ["1.2k\n(0.5 s)", "2.4k\n(1 s)", "4.3k\n(2 s)", "13k\n(5 s)", "33k\n(10 s)"])
ax.minorticks_off()
ax.set_xlim(right=60000)
ax.set_xlabel("Batch size (requests), from all reads in a trace interval", color=MUTED)
ax.set_ylabel("p99 completion time (min)", color=MUTED)
ax.set_ylim(bottom=0)
ax.grid(axis="y", color=GRID, lw=.8)
ax.text(0.02, 0.95, "solid: simulated (queue 8)   dashed: lower bound", transform=ax.transAxes, fontsize=11, color=MUTED, va="top")
ax.set_title("Smallest feasible SLO grows with the batch: one batch, one reader", loc="left", fontsize=14, color=INK, pad=14)
fig.savefig(OUT / "fig_batch_slo.png", dpi=300, bbox_inches="tight")
print("ok")
