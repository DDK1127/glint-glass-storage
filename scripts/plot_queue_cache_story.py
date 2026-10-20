"""English, high-resolution figures for results/queue-cache-story.

Run after run_queue_cache_story.py and run_reader_side_curves.py (the cache-motivation
figures reuse results/reader-side-curves, same setting: read overhead 1 s,
light load ~0.28 req/s, heavy load ~0.85 req/s).
"""
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/queue-cache-story"
CURVES = ROOT / "results/reader-side-curves"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE = "#2a78d6", "#eb6834"   # validated categorical slots 1-2
DPI = 300
plt.rcParams.update({"font.family": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"], "font.size": 13,
                     "axes.edgecolor": GRID, "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": MUTED,
                     "axes.spines.top": False, "axes.spines.right": False})
LOADS = ["Light load\n(0.28 req/s)", "Heavy load\n(0.85 req/s)"]

A, B = {}, {}
for r in csv.DictReader(open(OUT / "aggregate.csv")):
    key = (r["load"], int(float(r["queue_slots"])), int(float(r["cache_slots"])))
    (A if r["part"] == "A" else B)[key] = {k: float(v) for k, v in r.items() if k not in ("part", "load")}


def bars(path, title, groups, series, ylabel, fmt="{:.0f}", ymax=None, max_tick=None):
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    x = np.arange(len(groups))
    w = 0.7 / len(series)
    top = max(v for _, _, vals in series for v in vals)
    for i, (label, color, vals) in enumerate(series):
        bs = ax.bar(x + (i - (len(series) - 1) / 2) * (w + 0.02), vals, w, color=color, label=label)
        for b in bs:
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + top * 0.02, fmt.format(b.get_height()),
                    ha="center", fontsize=13, color=INK)
    ax.set_xticks(x, groups)
    ax.set_ylim(0, ymax or top * 1.3)
    if max_tick is not None:
        ax.set_yticks([t for t in ax.get_yticks() if t <= max_tick])
    ax.set_ylabel(ylabel, color=MUTED)
    ax.grid(axis="y", color=GRID, lw=.8)
    ax.set_axisbelow(True)
    if len(series) > 1:
        ax.legend(frameon=False, loc="upper left", ncol=len(series), fontsize=12)
    ax.set_title(title, loc="left", fontsize=14, color=INK, pad=14)
    fig.savefig(OUT / path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)


# ---- Part A: reader-front queue
bars("a1_queue_p99.png", "Reader-front queue: no gain at light load, -17% at heavy load", LOADS,
     [("No queue (direct hand-off)", BLUE, [A[("light", 0, 0)]["p99_s"], A[("heavy", 0, 0)]["p99_s"]]),
      ("Queue, 8 slots", ORANGE, [A[("light", 8, 0)]["p99_s"], A[("heavy", 8, 0)]["p99_s"]])],
     "p99 latency (s)")

bars("a2_queue_full.png", "Heavy load: the queue fills up and shuttles still wait at the reader",
     ["No queue", "Queue, 8 slots", "Queue, 16 slots"],
     [("", BLUE, [100 * A[("heavy", k, 0)]["shuttle_wait_at_reader"] for k in (0, 8, 16)])],
     "Shuttle time waiting at the reader (%)", fmt="{:.0f}%", ymax=80)

bars("a3_reader_waiting.png", "Why the queue helps little: the reader rarely waits for a hand-off", LOADS,
     [("No queue", BLUE, [100 * A[("light", 0, 0)]["reader_waiting"], 100 * A[("heavy", 0, 0)]["reader_waiting"]]),
      ("Queue, 8 slots", ORANGE, [100 * A[("light", 8, 0)]["reader_waiting"], 100 * A[("heavy", 8, 0)]["reader_waiting"]])],
     "Reader idle while requests are pending (%)", fmt="{:.0f}%", ymax=60)

# ---- Part B: platter cache
gaps = np.asarray([float(r["gap_s"]) for r in csv.DictReader(open(CURVES / "reopen_gaps_baseline.csv"))
                   if float(r["overhead_s"]) == 1.0 and float(r["load_mult"]) == 0.9])
edges = [10, 30, 60, 300]
bars("b0_reopen.png", "After a platter is put away, how soon is it requested again?",
     ["within 10 s", "within 30 s", "within 1 min", "within 5 min"],
     [("", BLUE, [(gaps <= e).mean() * 100 for e in edges])],
     "Share of re-openings (%)", fmt="{:.0f}%", ymax=115, max_tick=100)

curves = {}
for r in csv.DictReader(open(CURVES / "aggregate.csv")):
    if float(r["overhead_s"]) == 1.0:
        curves[(float(r["load_mult"]), r["variant"])] = float(r["p99_s"])
bars("b1_cache_p99.png", "LRU platter cache: faster at light load, slower at heavy load", LOADS,
     [("No cache", BLUE, [curves[(0.3, "baseline")], curves[(0.9, "baseline")]]),
      ("LRU cache, 8 platters", ORANGE, [curves[(0.3, "lru_8")], curves[(0.9, "lru_8")]])],
     "p99 latency (s)")

base, cache = B[("heavy", 8, 0)], B[("heavy", 8, 8)]
bars("b2_requests_per_open.png", "Heavy load: platters opened from the cache serve few requests",
     ["No cache", "With cache:\nfetched from shelf", "With cache:\ntaken from cache"],
     [("", BLUE, [base["requests_per_open"], cache["shelf_requests_per_open"], cache["cache_requests_per_open"]])],
     "Requests served per platter opening", fmt="{:.1f}")

for old in ("simple_1_reopen.png", "simple_2_cache_p99.png", "b1_requests_per_open.png"):
    (OUT / old).unlink(missing_ok=True)   # replaced by the English b0/b1/b2 figures
print("ok")

# ---- Queue diagnosis (scripts/probes/queue_diagnosis.py)
diag = json.loads((OUT / "queue_diagnosis.json").read_text())
light = diag["light"]["stuck"]
bars("a4_why_queue_empty.png", "Light load: why the queue is empty while requests wait",
     ["Its platter is still\nbeing fetched", "Its shuttle is busy\nreturning another platter", "Other"],
     [("", BLUE, [100 * light.get("platter being fetched (shuttle on the way)", 0),
                  100 * light.get("platter at home, its shuttle busy returning", 0),
                  100 * (1 - light.get("platter being fetched (shuttle on the way)", 0)
                         - light.get("platter at home, its shuttle busy returning", 0))])],
     "Share of reader idle time (%)", fmt="{:.0f}%", ymax=80)

def occ(load, lo, hi):
    q = diag[load]["queue_length_share"]
    return 100 * sum(v for k, v in q.items() if lo <= int(k) <= hi)

bars("a5_queue_occupancy.png", "Queue occupancy: mostly empty at light load, mostly full at heavy load",
     ["Empty", "1-7 platters", "Full (8 platters)"],
     [("Light load", BLUE, [occ("light", 0, 0), occ("light", 1, 7), occ("light", 8, 8)]),
      ("Heavy load", ORANGE, [occ("heavy", 0, 0), occ("heavy", 1, 7), occ("heavy", 8, 8)])],
     "Share of time (%)", fmt="{:.0f}%", ymax=110, max_tick=100)
print("ok")
