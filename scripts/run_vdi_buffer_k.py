"""Sweep the read-ahead feeder buffer size K on the Fujitsu VDI trace."""
import csv
from dataclasses import replace
import json
from pathlib import Path
from statistics import median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from glass_sim import vdi_workload as V
from glass_sim.io_scheduler import IOConfig, IOSimulation, SilicaFIFO

ROOT = Path(__file__).resolve().parents[1]
cfg = json.loads((ROOT / "experiments/vdi-buffer-k/config.json").read_text())
OUT = ROOT / "results/vdi-buffer-k"
OUT.mkdir(parents=True, exist_ok=True)
base = IOConfig()
reads = V.load_reads(ROOT / V.TRACE)
n, k = len(reads[0]), cfg["online"]["requests"]
starts = np.linspace(0, n - k - 1, cfg["online"]["windows"]).astype(int)
rows = []
for m in cfg["mappings"]:
    plat = V.platter_map(reads[1], base.platters, m)
    cap = median(k / IOSimulation(base, V.requests(reads, plat, int(st), k), SilicaFIFO()).run()["makespan_s"] for st in starts)
    for load in cfg["online"]["loads"]:
        for st in starts:
            scale = (k / (cap * load)) / (reads[0][st + k - 1] - reads[0][st])
            reqs = V.requests(reads, plat, int(st), k, time_scale=scale)
            for b in cfg["buffer_slots"]:
                c = replace(base, buffer_slots=b)
                s = IOSimulation(c, reqs, SilicaFIFO()).run()
                T = s["shuttle_time_s"]
                rows.append(dict(mapping=m, load=load, start=int(st), buffer_slots=b, mean_s=s["mean_s"], p99_s=s["p99_s"],
                                 reader_starved=s["reader_starved_fraction"], reader_busy=s["reader_busy_fraction"],
                                 shuttle_gate=s["gate_wait_s"] / T, shuttle_idle=s["shuttle_idle_s"] / T, trips=s["trips"]))
with open(OUT / "runs.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
agg = []
for m in cfg["mappings"]:
    for load in cfg["online"]["loads"]:
        cell = []
        for b in cfg["buffer_slots"]:
            sel = [r for r in rows if r["mapping"] == m and r["load"] == load and r["buffer_slots"] == b]
            cell.append(dict(mapping=m, load=load, buffer_slots=b,
                             **{x: median(r[x] for r in sel) for x in ("mean_s", "p99_s", "reader_starved", "shuttle_gate", "shuttle_idle", "trips")}))
        best = min(a["mean_s"] for a in cell)
        knee = min(a["buffer_slots"] for a in cell if a["mean_s"] <= 1.05 * best)
        for a in cell:
            a["knee_k"] = knee
        agg.extend(cell)
with open(OUT / "aggregate.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(agg[0]))
    w.writeheader()
    w.writerows(agg)
for a in agg:
    print({x: (round(v, 3) if isinstance(v, float) else v) for x, v in a.items()})
