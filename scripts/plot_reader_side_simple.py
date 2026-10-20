"""Four simple single-panel figures for results/reader-side-curves (read overhead 1 s).

Light load = load multiplier 0.3 (~0.28 requests/s); heavy load = 0.9 (~0.85 requests/s).
Run after run_reader_side_curves.py.
"""
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
BLUE, ORANGE = "#2a78d6", "#eb6834"
OVERHEAD, LIGHT, HEAVY = 1.0, 0.3, 0.9
for name in ("PingFang TC", "Heiti TC", "Arial Unicode MS"):
    if any(f.name == name for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = name
        break
plt.rcParams.update({"font.size": 13, "axes.edgecolor": GRID, "axes.labelcolor": INK, "xtick.color": INK,
                     "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False})

agg = {}
for r in csv.DictReader(open(OUT / "aggregate.csv")):
    if float(r["overhead_s"]) == OVERHEAD:
        agg[(float(r["load_mult"]), r["variant"])] = {k: float(v) for k, v in r.items() if k != "variant"}


def grouped(path, title, groups, series, ylabel, fmt="{:.0f}", ymax=None):
    """groups: x labels; series: [(label, color, [values per group])]."""
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    x = np.arange(len(groups))
    w = 0.36
    top = max(v for _, _, vals in series for v in vals)
    for i, (label, color, vals) in enumerate(series):
        bars = ax.bar(x + (i - (len(series) - 1) / 2) * (w + 0.02), vals, w, color=color, label=label)
        for b in bars:
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + top * 0.02, fmt.format(b.get_height()),
                    ha="center", fontsize=13, color=INK)
    ax.set_xticks(x, groups)
    ax.set_ylim(0, ymax or top * 1.3)
    if ymax:
        ax.set_yticks([t for t in ax.get_yticks() if t <= 100])
    ax.set_ylabel(ylabel, color=MUTED)
    ax.grid(axis="y", color=GRID, lw=.8)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="upper left", ncol=len(series))
    ax.set_title(title, loc="left", fontsize=14, color=INK, pad=14)
    fig.savefig(OUT / path, dpi=180, bbox_inches="tight")
    plt.close(fig)


# 1. Re-opened soon after being put away (baseline, heavy load)
gaps = [float(r["gap_s"]) for r in csv.DictReader(open(OUT / "reopen_gaps_baseline.csv"))
        if float(r["overhead_s"]) == OVERHEAD and float(r["load_mult"]) == HEAVY]
gaps = np.asarray(gaps)
edges = [10, 30, 60, 300]
fig, ax = plt.subplots(figsize=(7.5, 4.6))
vals = [(gaps <= e).mean() * 100 for e in edges]
bars = ax.bar(range(len(edges)), vals, 0.5, color=BLUE)
for b in bars:
    ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 2, f"{b.get_height():.0f}%", ha="center", fontsize=13, color=INK)
ax.set_xticks(range(len(edges)), ["10 秒內", "30 秒內", "1 分鐘內", "5 分鐘內"])
ax.set_ylim(0, 115)
ax.set_ylabel("佔所有「再次打開」的比例（%）", color=MUTED)
ax.grid(axis="y", color=GRID, lw=.8)
ax.set_axisbelow(True)
ax.set_title("一片玻璃讀完送走後，多快又被要回來", loc="left", fontsize=14, color=INK, pad=14)
fig.savefig(OUT / "simple_1_reopen.png", dpi=180, bbox_inches="tight")
plt.close(fig)

# 2. Cache helps at light load, hurts at heavy load (p99)
grouped("simple_2_cache_p99.png", "加上 cache：輕載變快，重載變慢",
        ["輕載", "重載"],
        [("沒有 cache", BLUE, [agg[(LIGHT, "baseline")]["p99_s"], agg[(HEAVY, "baseline")]["p99_s"]]),
         ("LRU cache（8 片）", ORANGE, [agg[(LIGHT, "lru_8")]["p99_s"], agg[(HEAVY, "lru_8")]["p99_s"]])],
        "最慢 1% 的等待（秒）")

# 3. Why: fewer fetches, more openings (heavy load)
b, c = agg[(HEAVY, "baseline")], agg[(HEAVY, "lru_8")]
grouped("simple_3_opens.png", "重載時：cache 讓車少跑，卻讓玻璃被打開更多次",
        ["沒有 cache", "LRU cache（8 片）"],
        [("車搬運的趟數", BLUE, [b["fetch_trips"], c["fetch_trips"]]),
         ("玻璃被打開的次數", ORANGE, [b["opens"], c["opens"]])],
        "次數（每 2,000 個請求）")

# 4. Reader busy: the reason the effect flips
grouped("simple_4_reader_busy.png", "cache 讓 Reader 更忙：輕載還有空，重載就塞住",
        ["輕載", "重載"],
        [("沒有 cache", BLUE, [100 * agg[(LIGHT, "baseline")]["reader_busy"], 100 * agg[(HEAVY, "baseline")]["reader_busy"]]),
         ("LRU cache（8 片）", ORANGE, [100 * agg[(LIGHT, "lru_8")]["reader_busy"], 100 * agg[(HEAVY, "lru_8")]["reader_busy"]])],
        "Reader 忙碌（%）", fmt="{:.0f}%", ymax=125)
print("rates:", agg[(LIGHT, "baseline")]["rate_req_s"], agg[(HEAVY, "baseline")]["rate_req_s"])
print("reopen", dict(zip(edges, [round(v) for v in vals])))
