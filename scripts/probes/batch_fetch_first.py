"""Probe: in one batch of real requests, how much do return trips cost? (fetch-first vs return-first)"""
import json
from dataclasses import replace
from pathlib import Path
from statistics import median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np

from glass_sim import systor17 as S
from glass_sim.io_scheduler import IOConfig, IOSimulation, SilicaFIFO

ROOT = Path(__file__).resolve().parents[2]
CFG = json.loads((ROOT / "experiments/batch-story/config.json").read_text())

if __name__ == "__main__":
    d = S.load("20160222", root=ROOT / S.RAW)
    b = CFG["batch"]
    for placement in CFG["placements"]:
        plat = S.PLACEMENTS[placement](d, IOConfig().platters, seed=CFG["seed"])
        for size in (2000, 4000):
            rng = np.random.default_rng(CFG["seed"])
            batches = [S.sample(d, plat, S.day_start_hour(d, h), b["span_s"], size, rng) for h in b["windows_start_hour"]]
            for pr in ("return_first", "fetch_first"):
                c = replace(IOConfig(), request_overhead_s=1.0, buffer_slots=8, return_priority=pr)
                res = [IOSimulation(c, S.to_requests(*x), SilicaFIFO()).run() for x in batches]
                m = lambda k: median(r[k] for r in res)
                print(placement, size, f"{pr:12s} makespan {m('makespan_s'):6.0f} (LB {m('lower_bound_s'):5.0f}) mean {m('mean_s'):5.0f} p99 {m('p99_s'):5.0f}",
                      f"reader waiting {m('reader_starved_fraction'):.0%} blocked {median(r['reader_blocked_s'] / r['makespan_s'] for r in res):.1%}")
