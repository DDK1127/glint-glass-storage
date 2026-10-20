"""Queue observations on the Fujitsu VDI trace only (no synthetic workloads)."""
import csv
import json
from pathlib import Path
from statistics import median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from glass_sim import vdi_workload as V
from glass_sim.io_scheduler import IOConfig, IOSimulation, SilicaFIFO

ROOT = Path(__file__).resolve().parents[1]
cfg = json.loads((ROOT / "experiments/vdi-queue-obs/config.json").read_text())
OUT = ROOT / "results/vdi-queue-obs"
OUT.mkdir(parents=True, exist_ok=True)
c = IOConfig()
reads = V.load_reads(ROOT / V.TRACE)
n = len(reads[0])


def tail_share(sim, s):
    """Share of reader starvation after half the shuttles dispatched their last trip."""
    last = sorted(max((t["dispatch_s"] for t in sim.trips if t["shuttle"] == i), default=0.0) for i in range(c.shuttles))
    cut = last[c.shuttles // 2 - 1]
    tr = sim.trace
    starved = sum(b[0] - a[0] for a, b in zip(tr, tr[1:]) if a[0] >= cut and a[1] == "starved")
    return starved / s["reader_starved_s"] if s["reader_starved_s"] else 0.0


def row(s, **extra):
    T = s["shuttle_time_s"]
    return dict(**extra, trips=s["trips"], requests_per_trip=s["requests_per_trip"], makespan_s=s["makespan_s"],
                gap_vs_lb=s["gap_vs_lb"], mean_s=s["mean_s"], p99_s=s["p99_s"],
                reader_busy=s["reader_busy_fraction"], reader_starved=s["reader_starved_fraction"],
                shuttle_idle=s["shuttle_idle_s"] / T, shuttle_restricted_idle=s["shuttle_restricted_idle_s"] / T,
                shuttle_gate=s["gate_wait_s"] / T, shuttle_traffic=s["traffic_wait_s"] / T)


burst, online = [], []
for m in cfg["mappings"]:
    plat = V.platter_map(reads[1], c.platters, m)
    for st in np.linspace(0, n - cfg["burst"]["requests"] - 1, cfg["burst"]["windows"]).astype(int):
        sim = IOSimulation(c, V.requests(reads, plat, int(st), cfg["burst"]["requests"]), SilicaFIFO(), record=True)
        s = sim.run()
        trips = [0] * c.shuttles
        for t in sim.trips:
            trips[t["shuttle"]] += 1
        burst.append(row(s, mapping=m, start=int(st), busiest_zone_trip_share=max(trips) / sum(trips),
                         starvation_in_tail=tail_share(sim, s)))
    k = cfg["online"]["requests"]
    starts = np.linspace(0, n - k - 1, cfg["online"]["windows"]).astype(int)
    cap = median(k / IOSimulation(c, V.requests(reads, plat, int(st), k), SilicaFIFO()).run()["makespan_s"] for st in starts)
    for load in cfg["online"]["loads"]:
        for st in starts:
            scale = (k / (cap * load)) / (reads[0][st + k - 1] - reads[0][st])
            s = IOSimulation(c, V.requests(reads, plat, int(st), k, time_scale=scale), SilicaFIFO()).run()
            online.append(row(s, mapping=m, load=load, start=int(st), capacity_req_s=cap))


def dump(name, rows):
    with open(OUT / name, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


dump("burst_runs.csv", burst)
dump("online_runs.csv", online)
summary = dict(burst={}, online={})
for m in cfg["mappings"]:
    sel = [r for r in burst if r["mapping"] == m]
    summary["burst"][m] = {k: median(r[k] for r in sel) for k in sel[0] if k not in ("mapping", "start")}
    for load in cfg["online"]["loads"]:
        sel = [r for r in online if r["mapping"] == m and r["load"] == load]
        summary["online"][f"{m}@{load}"] = {k: median(r[k] for r in sel) for k in sel[0] if k not in ("mapping", "start", "load")}
(OUT / "summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=1))
