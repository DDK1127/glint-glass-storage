"""Minimal I/O-scheduling headroom study: B0/B1 vs a makespan lower bound."""
import csv
import json
from pathlib import Path
from statistics import median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from glass_sim.io_scheduler import SCHEDULERS, IOConfig, IOSimulation, make_burst

ROOT = Path(__file__).resolve().parents[1]
cfg = json.loads((ROOT / "experiments/io-sched-min/config.json").read_text())
out = ROOT / "results/io-sched-min"
out.mkdir(parents=True, exist_ok=True)
c = IOConfig()
rows = []
for scen, k in cfg["scenarios"].items():
    for seed in cfg["seeds"]:
        reqs = make_burst(c, cfg["requests"], seed, platters=k)
        for name in cfg["schedulers"]:
            s = IOSimulation(c, reqs, SCHEDULERS[name]()).run()
            T = s["shuttle_time_s"]
            s.update(scenario=scen, seed=seed,
                     shuttle_loaded=s["loaded_move_s"] / T, shuttle_empty=s["empty_move_s"] / T,
                     shuttle_traffic=s["traffic_wait_s"] / T, shuttle_gate=s["gate_wait_s"] / T,
                     shuttle_idle=s["shuttle_idle_s"] / T, shuttle_restricted_idle=s["shuttle_restricted_idle_s"] / T)
            rows.append(s)
keys = list(rows[0])
with open(out / "runs.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=keys)
    w.writeheader()
    w.writerows(rows)
metrics = ["makespan_s", "lower_bound_s", "gap_vs_lb", "mean_s", "p99_s", "trips", "requests_per_trip",
           "reader_busy_fraction", "reader_starved_fraction", "shuttle_loaded", "shuttle_empty",
           "shuttle_traffic", "shuttle_gate", "shuttle_idle", "shuttle_restricted_idle", "decision_cpu_us"]
agg = []
for scen in cfg["scenarios"]:
    for name in cfg["schedulers"]:
        sel = [r for r in rows if r["scenario"] == scen and r["scheduler"] == name]
        agg.append(dict(scenario=scen, scheduler=name, runs=len(sel), **{m: median(r[m] for r in sel) for m in metrics}))
with open(out / "aggregate.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(agg[0]))
    w.writeheader()
    w.writerows(agg)
b1 = [a for a in agg if a["scheduler"] == "B1_silica"]
verdict = "DROP" if all(a["gap_vs_lb"] < 0.10 for a in b1) else "HEADROOM"
(out / "summary.json").write_text(json.dumps(dict(verdict=verdict, b1_gap={a["scenario"]: a["gap_vs_lb"] for a in b1}), indent=2))
for a in agg:
    print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in a.items()})
print("verdict", verdict)
