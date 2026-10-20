"""Light vs heavy load from the trace itself: 1-second batches from the quietest and busiest hour."""
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
CFG = json.loads((ROOT / "experiments/batch-load/config.json").read_text())
OUT = ROOT / "results/batch-load"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    d = S.load("20160222", root=ROOT / S.RAW)
    plat = S.PLACEMENTS["contig_balanced"](d, IOConfig().platters, seed=CFG["seed"])
    rm, b = CFG["read_model"], CFG["batch"]
    rows = []
    for load, spec in CFG["loads"].items():
        for k, off in enumerate(b["offsets_min"]):
            start = S.day_start_hour(d, spec["hour"]) + 60 * off
            lo, hi = np.searchsorted(d["t"], [start, start + b["interval_s"]])
            idx = np.arange(lo, hi)
            reqs = S.to_requests(np.zeros(len(idx)), plat[idx], d["size"][idx], offset=d["off"][idx] % S.PLATTER_BYTES)
            for mbs in rm["read_mb_s"]:
                for v, vc in CFG["variants"].items():
                    c = replace(IOConfig(), track_data_bytes=rm["track_data_bytes"], track_read_bytes=rm["track_read_bytes"],
                                track_seek_s=rm["track_seek_s"], read_mb_s=float(mbs), **vc)
                    sim = IOSimulation(c, reqs, SilicaFIFO())
                    s = sim.run()
                    rows.append(dict(load=load, window=k, read_mb_s=mbs, variant=v, requests=len(idx),
                                     platters=len(set(plat[idx].tolist())), tracks=s["tracks_read"],
                                     p50_s=float(np.median(sim.done_s)), p99_s=quantile(sim.done_s, .99),
                                     makespan_s=s["makespan_s"], lower_bound_s=s["lower_bound_s"],
                                     reader_busy=s["reader_busy_fraction"], reader_waiting=s["reader_starved_fraction"]))
    with open(OUT / "runs.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    keys = [k for k in rows[0] if k not in ("load", "window", "read_mb_s", "variant")]
    agg = []
    for load in CFG["loads"]:
        for mbs in rm["read_mb_s"]:
            for v in CFG["variants"]:
                sel = [r for r in rows if r["load"] == load and r["read_mb_s"] == mbs and r["variant"] == v]
                agg.append(dict(load=load, read_mb_s=mbs, variant=v, **{k: median(r[k] for r in sel) for k in keys}))
    with open(OUT / "aggregate.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(agg[0]))
        wr.writeheader()
        wr.writerows(agg)
    for a in agg:
        print(f"{a['load']:5s} {a['read_mb_s']:3d}MB/s {a['variant']:14s} requests {a['requests']:5.0f} platters {a['platters']:3.0f} tracks {a['tracks']:5.0f}",
              f"p50 {a['p50_s']/60:4.1f} p99 {a['p99_s']/60:4.1f}min (LB {a['lower_bound_s']/60:4.1f}) busy {a['reader_busy']:.0%} waiting {a['reader_waiting']:.0%}")


if __name__ == "__main__":
    main()
