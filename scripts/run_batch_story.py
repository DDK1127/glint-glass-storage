"""Queue and cache under one batch of real requests issued at t=0 (no time stretching)."""
from concurrent.futures import ProcessPoolExecutor
import csv
from dataclasses import replace
import json
from pathlib import Path
from statistics import mean, median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent / "probes"))

import numpy as np

from glass_sim import systor17 as S
from glass_sim.io_scheduler import IOConfig, IOSimulation, SilicaFIFO
from queue_diagnosis import Diagnose

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "experiments/batch-story/config.json").read_text())
OUT = ROOT / "results/batch-story"
BATCHES = {}


def init(b):
    BATCHES.update(b)


def run(job):
    placement, overhead, size, w, variant = job
    rel_t, plat, sz = BATCHES[(placement, size, w)]
    c = replace(IOConfig(), request_overhead_s=overhead, **CFG["variants"][variant])
    diag = Diagnose()
    sim = IOSimulation(c, S.to_requests(rel_t, plat, sz), SilicaFIFO(), observer=diag)
    s = sim.run()
    shelf = [len(t["requests"]) for t in sim.trips if not t.get("from_cache")]
    cache = [len(t["requests"]) for t in sim.trips if t.get("from_cache")]
    stuck = sum(diag.stuck.values()) or 1.0
    return dict(placement=placement, overhead_s=overhead, size=size, window=w, variant=variant, makespan_s=s["makespan_s"], mean_s=s["mean_s"], p99_s=s["p99_s"],
                lower_bound_s=s["lower_bound_s"], opens=len(sim.trips), fetch_trips=s["fetch_trips"],
                requests_per_open=size / len(sim.trips), reader_busy=s["reader_busy_fraction"],
                reader_waiting=s["reader_starved_fraction"], shuttle_wait_at_reader=s["gate_wait_s"] / s["shuttle_time_s"],
                distinct_platters=len(set(plat.tolist())),
                queue_empty=diag.queue_len[0] / diag.total, queue_full=diag.queue_len[8] / diag.total,
                stuck_in_transit=diag.stuck.get("platter being fetched (shuttle on the way)", 0) / stuck,
                stuck_shuttle_returning=diag.stuck.get("platter at home, its shuttle busy returning", 0) / stuck,
                shelf_requests_per_open=mean(shelf) if shelf else 0.0, cache_requests_per_open=mean(cache) if cache else 0.0,
                shuttle_returning=diag.shuttle["returning"] / sum(diag.shuttle.values()))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    d = S.load("20160222", root=ROOT / S.RAW)
    b = CFG["batch"]
    batches = {}
    for placement in CFG["placements"]:
        plat = S.PLACEMENTS[placement](d, IOConfig().platters, seed=CFG["seed"])
        for size in b["sizes"]:
            rng = np.random.default_rng(CFG["seed"])
            for w, h in enumerate(b["windows_start_hour"]):
                batches[(placement, size, w)] = S.sample(d, plat, S.day_start_hour(d, h), b["span_s"], size, rng)
    init(batches)
    jobs = [(p, o, size, w, v) for (p, size, w) in batches for o in CFG["request_overhead_s"] for v in CFG["variants"]]
    with ProcessPoolExecutor(8, initializer=init, initargs=(batches,)) as pool:
        rows = list(pool.map(run, jobs, chunksize=1))
    with open(OUT / "runs.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    keys = [k for k in rows[0] if k not in ("placement", "overhead_s", "size", "window", "variant")]
    agg = []
    for p in CFG["placements"]:
        for o in CFG["request_overhead_s"]:
            for size in b["sizes"]:
                for v in CFG["variants"]:
                    sel = [r for r in rows if r["placement"] == p and r["overhead_s"] == o and r["size"] == size and r["variant"] == v]
                    agg.append(dict(placement=p, overhead_s=o, size=size, variant=v, **{k: median(r[k] for r in sel) for k in keys}))
    with open(OUT / "aggregate.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(agg[0]))
        wr.writeheader()
        wr.writerows(agg)
    for a in agg:
        print(a["overhead_s"], a["size"], f"{a['variant']:14s} makespan {a['makespan_s']:6.0f} (LB {a['lower_bound_s']:5.0f}) mean {a['mean_s']:5.0f} p99 {a['p99_s']:6.0f}",
              f"platters {a['distinct_platters']:.0f} opens {a['opens']:4.0f} fetch {a['fetch_trips']:4.0f} req/open {a['requests_per_open']:5.1f}",
              f"| reader busy {a['reader_busy']:.0%} waiting {a['reader_waiting']:.0%} | queue empty {a['queue_empty']:.0%} full {a['queue_full']:.0%}",
              f"| stuck transit {a['stuck_in_transit']:.0%} returning {a['stuck_shuttle_returning']:.0%} | shuttle@reader {a['shuttle_wait_at_reader']:.0%} returning {a['shuttle_returning']:.0%}",
              f"| cache req/open {a['cache_requests_per_open']:.1f}")


if __name__ == "__main__":
    main()
