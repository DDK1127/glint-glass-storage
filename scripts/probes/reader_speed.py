"""Probe: how much room do queue/cache have at reader 30 / 60 / 210 MB/s?

Fixed-size batches of consecutive real reads (N from a start time, all issued at t=0),
track read model, contiguous placement.
"""
from dataclasses import replace
from pathlib import Path
from statistics import median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np

from glass_sim import systor17 as S
from glass_sim.io_scheduler import IOConfig, IOSimulation, SilicaFIFO, quantile

ROOT = Path(__file__).resolve().parents[2]
VARIANTS = {"no queue": dict(buffer_slots=0), "queue 8": dict(buffer_slots=8),
            "queue 8 + LRU 8": dict(buffer_slots=8, cache_slots=8)}

if __name__ == "__main__":
    d = S.load("20160222", root=ROOT / S.RAW)
    plat = S.PLACEMENTS["contig_balanced"](d, IOConfig().platters, seed=1)
    for n in (2000, 5000):
        batches = []
        for h in (8, 9, 10, 11, 12, 13):
            lo = np.searchsorted(d["t"], S.day_start_hour(d, h))
            idx = np.arange(lo, lo + n)
            batches.append(S.to_requests(np.zeros(n), plat[idx], d["size"][idx], offset=d["off"][idx] % S.PLATTER_BYTES))
        for mbs in (30, 60, 210):
            for name, v in VARIANTS.items():
                c = replace(IOConfig(), track_data_bytes=10_000_000, read_mb_s=float(mbs), **v)
                res = []
                for reqs in batches:
                    sim = IOSimulation(c, reqs, SilicaFIFO())
                    s = sim.run()
                    res.append((s["makespan_s"], s["lower_bound_s"], quantile(sim.done_s, .99), float(np.mean(sim.done_s)),
                                s["reader_busy_fraction"], s["reader_starved_fraction"], s["tracks_read"]))
                m = lambda i: median(r[i] for r in res)
                print(f"N={n} {mbs:3d} MB/s {name:16s} makespan {m(0)/60:5.1f}min LB {m(1)/60:5.1f} gap {100*(m(0)/m(1)-1):4.0f}%",
                      f"mean {m(3)/60:4.1f} p99 {m(2)/60:5.1f} reader busy {m(4):.0%} waiting {m(5):.0%} tracks {m(6):.0f}")
