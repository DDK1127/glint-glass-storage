"""Observation 3 check: reader-state timeline, gate waits during large reads, buffer sweep."""
import csv
from dataclasses import replace
import json
from pathlib import Path
from statistics import median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Patch
from matplotlib.ticker import MaxNLocator

from glass_sim.io_scheduler import IOConfig, IOSimulation, SilicaFIFO, make_burst

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/io-sched-min"
LARGE_READ_S = 60.0       # a read longer than this counts as a large-file read (~1.8 GB at 30 MB/s)
AFTER_WINDOW_S = 300.0    # "starved soon after a large read" window
SEEDS = range(1, 11)
BUFFERS = (0, 4, 8, 16, 32, 64, 128)
SCENARIOS = {"independent": None, "restore_k160": 160}

INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
COLORS = dict(read="#2a78d6", large="#6250d6", mount="#c3c2b7", starved="#eb6834", empty="#f1f0ec")
for name in ("PingFang TC", "Heiti TC", "Arial Unicode MS"):
    if any(f.name == name for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = name
        break
plt.rcParams.update({"font.size": 11, "axes.edgecolor": GRID, "axes.labelcolor": INK, "xtick.color": MUTED,
                     "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False})


def shares(cfg, sim):
    """Where entrance waits and reader starvation fall relative to large-file reads."""
    tot = gate = gate_large = starved = starved_after = large_time = 0.0
    last_large_end = -1e18
    for (t, st, size, _, waiting, _), nxt in zip(sim.trace, sim.trace[1:]):
        dt = nxt[0] - t
        big = st == "read" and cfg.read_time(size) > LARGE_READ_S
        tot += dt
        gate += waiting * dt
        if big:
            large_time += dt
            gate_large += waiting * dt
            last_large_end = nxt[0]
        if st == "starved":
            starved += dt
            starved_after += dt if t - last_large_end < AFTER_WINDOW_S else 0.0
    return dict(large_read_time=large_time / tot, gate_wait_during_large=gate_large / gate if gate else 0.0,
                starved_fraction=starved / tot, starved_soon_after_large=starved_after / starved if starved else 0.0)


def timeline(cfg, scenario, seed, path):
    sim = IOSimulation(cfg, make_burst(cfg, 400, seed, platters=SCENARIOS[scenario]), SilicaFIFO(), record=True)
    s = sim.run()
    tr = sim.trace
    fig, axes = plt.subplots(3, 1, figsize=(12, 6.2), sharex=True,
                             gridspec_kw=dict(height_ratios=[1, 1.4, 1.4], hspace=.35))
    band = axes[0]
    for (t, st, size, *_), nxt in zip(tr, tr[1:]):
        key = "large" if st == "read" and cfg.read_time(size) > LARGE_READ_S else \
              "read" if st == "read" else "starved" if st == "starved" else "empty" if st == "empty" else "mount"
        band.axvspan(t / 60, nxt[0] / 60, color=COLORS[key], lw=0)
    band.set_yticks([])
    band.set_title("Reader 狀態", loc="left", fontsize=11, color=INK)
    band.legend(handles=[Patch(color=COLORS[k], label=l) for k, l in
                         (("read", "讀取中"), ("large", "讀取大檔（> 60 秒）"), ("mount", "裝片／卸片／等出口"),
                          ("starved", "空等（有工作但沒片可讀）"))],
                ncol=4, frameon=False, fontsize=9.5, loc="lower left", bbox_to_anchor=(0, 1.18))
    times = [x[0] / 60 for x in tr]
    axes[1].step(times, [x[4] for x in tr], where="post", color=COLORS["starved"], lw=1.6)
    axes[1].set_ylabel("台")
    axes[1].set_title("在 reader 入口等著交貨的車", loc="left", fontsize=11, color=INK)
    axes[2].step(times, [x[3] for x in tr], where="post", color=COLORS["read"], lw=1.6)
    axes[2].axhline(cfg.buffer_slots, color=MUTED, lw=1, ls="--")
    axes[2].text(times[-1], cfg.buffer_slots + .3, f"容量 {cfg.buffer_slots}", ha="right", fontsize=9, color=MUTED)
    axes[2].set_ylabel("片")
    axes[2].set_title("Reader 前 buffer 裡等著被讀的 platter", loc="left", fontsize=11, color=INK)
    axes[2].set_xlabel("時間（分鐘）")
    for ax in axes[1:]:
        ax.grid(axis="y", color=GRID, lw=.8)
        ax.set_ylim(bottom=0)
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return s


def main():
    base = IOConfig()
    rows = []
    for scenario, k in SCENARIOS.items():
        for seed in SEEDS:
            sim = IOSimulation(base, make_burst(base, 400, seed, platters=k), SilicaFIFO(), record=True)
            s = sim.run()
            rows.append(dict(scenario=scenario, seed=seed, **shares(base, sim)))
    with open(OUT / "obs3_shares.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    sweep = []
    for scenario, k in SCENARIOS.items():
        for b in BUFFERS:
            cfg = replace(base, buffer_slots=b)
            res = [IOSimulation(cfg, make_burst(cfg, 400, sd, platters=k), SilicaFIFO()).run() for sd in SEEDS]
            sweep.append(dict(scenario=scenario, buffer_slots=b,
                              makespan_s=median(r["makespan_s"] for r in res),
                              gap_vs_lb=median(r["gap_vs_lb"] for r in res),
                              reader_starved_fraction=median(r["reader_starved_fraction"] for r in res),
                              shuttle_gate=median(r["gate_wait_s"] / r["shuttle_time_s"] for r in res)))
    with open(OUT / "buffer_sweep.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(sweep[0]))
        w.writeheader()
        w.writerows(sweep)
    for scenario in SCENARIOS:
        timeline(base, scenario, 1, OUT / f"fig_timeline_{scenario}.png")
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    labels = dict(independent="檔案各在不同 platter", restore_k160="檔案分散在 160 片")
    for scenario, color in zip(SCENARIOS, (COLORS["read"], COLORS["starved"])):
        sel = [r for r in sweep if r["scenario"] == scenario]
        xs = range(len(sel))
        ys = [100 * r["gap_vs_lb"] for r in sel]
        ax.plot(xs, ys, color=color, lw=2, marker="o", ms=6)
        ax.text(len(sel) - 1 + .15, ys[-1], labels[scenario], color=INK, fontsize=10, va="center")
    ax.set_xticks(range(len(BUFFERS)), [str(b) for b in BUFFERS])
    ax.set_xlabel("Reader 前 buffer 容量（片）")
    ax.set_ylabel("比下限慢（%）")
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", color=GRID, lw=.8)
    ax.set_title("Silica 排程（B1）：加大 buffer 能追回多少", loc="left", fontsize=11, color=INK)
    fig.savefig(OUT / "fig_buffer_sweep.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    summary = {sc: {m: median(r[m] for r in rows if r["scenario"] == sc)
                    for m in ("large_read_time", "gate_wait_during_large", "starved_fraction", "starved_soon_after_large")}
               for sc in SCENARIOS}
    (OUT / "obs3_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
