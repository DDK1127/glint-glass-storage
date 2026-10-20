"""Zone vs Zone + work stealing vs Non-Zone feeding one FIFO reader queue (SYSTOR'17 traces)."""
from concurrent.futures import ProcessPoolExecutor
import csv
from dataclasses import replace
import json
from pathlib import Path
from statistics import median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from glass_sim import systor17 as S
from glass_sim.io_scheduler import IOConfig, IOSimulation, SilicaFIFO

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "experiments/systor-dispatch/config.json").read_text())
OUT = ROOT / "results/systor-dispatch"
WINDOWS = {}


def init(w):
    WINDOWS.update(w)


def base(overhead, dispatch="zone"):
    return replace(IOConfig(), request_overhead_s=overhead, dispatch=dispatch,
                   ws_threshold=CFG["ws_params"]["ws_threshold"], ws_max_helpers=CFG["ws_params"]["ws_max_helpers"])


def capacity(job):
    placement, overhead, w = job
    rel_t, plat, size = WINDOWS[placement][w]
    return job, len(rel_t) / IOSimulation(base(overhead), S.to_requests(rel_t, plat, size), SilicaFIFO()).run()["makespan_s"]


def run(job):
    placement, overhead, w, dispatch, scale = job
    rel_t, plat, size = WINDOWS[placement][w]
    s = IOSimulation(base(overhead, dispatch), S.to_requests(rel_t, plat, size, scale), SilicaFIFO()).run()
    T = s["shuttle_time_s"]
    zones = np.bincount(plat // IOConfig().slots_per_row, minlength=8)
    return dict(placement=placement, overhead_s=overhead, window=w, dispatch=dispatch,
                mean_s=s["mean_s"], p99_s=s["p99_s"], trips=s["trips"], helper_trips=s["helper_trips"],
                reader_busy=s["reader_busy_fraction"], reader_starved=s["reader_starved_fraction"],
                shuttle_idle=s["shuttle_idle_s"] / T, shuttle_restricted_idle=s["shuttle_restricted_idle_s"] / T,
                shuttle_traffic=s["traffic_wait_s"] / T, shuttle_gate=s["gate_wait_s"] / T,
                contended_steps=s["contended_steps"], busiest_zone_share=zones.max() / zones.sum())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    d = S.load("20160222", root=ROOT / S.RAW)
    sc = CFG["sampling"]
    wins = {}
    for p in CFG["placements"]:
        plat = S.PLACEMENTS[p](d, IOConfig().platters, seed=CFG["seed"])
        rng = np.random.default_rng(CFG["seed"])
        wins[p] = [S.sample(d, plat, S.day_start_hour(d, h), sc["span_s"], sc["requests"], rng) for h in sc["windows_start_hour"]]
    init(wins)
    with ProcessPoolExecutor(8, initializer=init, initargs=(wins,)) as pool:
        caps = dict(pool.map(capacity, [(p, o, w) for p in wins for o in CFG["request_overhead_s"] for w in range(len(wins[p]))]))
        jobs = []
        for p in wins:
            for o in CFG["request_overhead_s"]:
                cap = median(caps[(p, o, w)] for w in range(len(wins[p])))
                for w, (rel_t, _, _) in enumerate(wins[p]):
                    scale = (len(rel_t) / (cap * CFG["load"])) / rel_t[-1]
                    jobs += [(p, o, w, disp, scale) for disp in CFG["dispatch"]]
        rows = list(pool.map(run, jobs, chunksize=2))
    with open(OUT / "runs.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    keys = [k for k in rows[0] if k not in ("placement", "overhead_s", "window", "dispatch")]
    agg = []
    for p in CFG["placements"]:
        for o in CFG["request_overhead_s"]:
            for disp in CFG["dispatch"]:
                sel = [r for r in rows if r["placement"] == p and r["overhead_s"] == o and r["dispatch"] == disp]
                agg.append(dict(placement=p, overhead_s=o, dispatch=disp, **{k: median(r[k] for r in sel) for k in keys}))
    with open(OUT / "aggregate.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(agg[0]))
        wr.writeheader()
        wr.writerows(agg)
    for a in agg:
        print(a["placement"], a["overhead_s"], f"{a['dispatch']:8s}", f"mean {a['mean_s']:7.0f}", f"p99 {a['p99_s']:7.0f}",
              f"reader busy {a['reader_busy']:.0%} starved {a['reader_starved']:.0%}",
              f"idle {a['shuttle_idle']:.0%} restricted {a['shuttle_restricted_idle']:.0%} traffic {a['shuttle_traffic']:.0%}",
              f"helpers {a['helper_trips']:.0f} busiest {a['busiest_zone_share']:.0%}")


if __name__ == "__main__":
    main()
