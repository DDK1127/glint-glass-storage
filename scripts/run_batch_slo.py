"""One batch of real requests with the track read model: completion times and SLO."""
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
from glass_sim.io_scheduler import IOConfig, IOSimulation, SilicaFIFO, quantile

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "experiments/batch-slo/config.json").read_text())
OUT = ROOT / "results/batch-slo"
BATCHES = {}


def init(b):
    BATCHES.update(b)


def config(mbs, variant):
    rm = CFG["read_model"]
    return replace(IOConfig(), track_data_bytes=rm["track_data_bytes"], track_read_bytes=rm["track_read_bytes"],
                   track_seek_s=rm["track_seek_s"], read_mb_s=float(mbs), **CFG["variants"][variant])


def run(job):
    mbs, interval, w, variant = job
    rel_t, plat, sz, off = BATCHES[(interval, w)]
    size = len(rel_t)
    c = config(mbs, variant)
    reqs = S.to_requests(np.zeros(size), plat, sz, offset=off)   # the whole batch is issued at t=0
    sim = IOSimulation(c, reqs, SilicaFIFO())
    s = sim.run()
    lat = np.asarray(sim.done_s)   # all arrive at t=0, so completion time = latency
    row = dict(read_mb_s=mbs, interval_s=interval, size=size, window=w, variant=variant, makespan_s=s["makespan_s"],
               lower_bound_s=s["lower_bound_s"], p50_s=float(np.median(lat)), p99_s=quantile(lat.tolist(), .99),
               mean_s=float(lat.mean()), platters=len(set(plat.tolist())), tracks_read=s["tracks_read"],
               requests_per_track=size / s["tracks_read"], opens=s["trips"], reader_busy=s["reader_busy_fraction"],
               reader_waiting=s["reader_starved_fraction"], shuttle_wait_at_reader=s["gate_wait_s"] / s["shuttle_time_s"])
    for m in CFG["slo_minutes"]:
        row[f"within_{m}min"] = float((lat <= 60 * m).mean())
    return row


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    d = S.load("20160222", root=ROOT / S.RAW)
    plat = S.PLACEMENTS["contig_balanced"](d, IOConfig().platters, seed=CFG["seed"])
    b = CFG["batch"]
    batches = {}
    for interval in b["interval_s"]:
        for w, h in enumerate(b["windows_start_hour"]):
            lo = np.searchsorted(d["t"], S.day_start_hour(d, h))
            idx = np.arange(lo, np.searchsorted(d["t"], d["t"][lo] + interval))
            batches[(interval, w)] = (d["t"][idx] - d["t"][idx[0]], plat[idx], d["size"][idx], d["off"][idx] % S.PLATTER_BYTES)
    init(batches)
    jobs = [(m, i, w, v) for m in CFG["read_model"]["read_mb_s"] for (i, w) in batches for v in CFG["variants"]]
    with ProcessPoolExecutor(8, initializer=init, initargs=(batches,)) as pool:
        rows = list(pool.map(run, jobs, chunksize=1))
    with open(OUT / "runs.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    keys = [k for k in rows[0] if k not in ("read_mb_s", "interval_s", "window", "variant")]
    agg = []
    for m in CFG["read_model"]["read_mb_s"]:
        for i in b["interval_s"]:
            for v in CFG["variants"]:
                sel = [r for r in rows if r["read_mb_s"] == m and r["interval_s"] == i and r["variant"] == v]
                agg.append(dict(read_mb_s=m, interval_s=i, variant=v, **{k: median(r[k] for r in sel) for k in keys}))
    with open(OUT / "aggregate.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(agg[0]))
        wr.writeheader()
        wr.writerows(agg)
    for a in agg:
        print(a["read_mb_s"], a["interval_s"], f"{a['size']:6.0f}", f"{a['variant']:14s} makespan {a['makespan_s']/60:5.1f}min (LB {a['lower_bound_s']/60:5.1f}) p50 {a['p50_s']/60:5.1f} p99 {a['p99_s']/60:5.1f}",
              f"platters {a['platters']:.0f} tracks {a['tracks_read']:.0f} req/track {a['requests_per_track']:.2f} busy {a['reader_busy']:.0%} waiting {a['reader_waiting']:.0%}",
              "within 10/20/30 min", f"{a['within_10min']:.0%}/{a['within_20min']:.0%}/{a['within_30min']:.0%}")


if __name__ == "__main__":
    main()
