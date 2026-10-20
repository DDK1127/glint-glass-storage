"""Probe: how much could the order in which platters are read lower the mean latency?

Reader-only view of one batch (transport ignored): each platter i takes
mount + tracks_i * track_time + unload and completes r_i requests. Compare the
mean request completion time for arrival order (FIFO by first request) with
Smith's rule (ascending reader time per request), which minimises it.
"""
from pathlib import Path
from statistics import median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np

from glass_sim import systor17 as S
from glass_sim.io_scheduler import IOConfig

ROOT = Path(__file__).resolve().parents[2]


def mean_completion(order, cost, reqs):
    t = done = 0.0
    for p in order:
        t += cost[p]
        done += t * reqs[p]
    return done / sum(reqs.values())


if __name__ == "__main__":
    d = S.load("20160222", root=ROOT / S.RAW)
    plat = S.PLACEMENTS["contig_balanced"](d, IOConfig().platters, seed=1)
    for mbs in (30, 60, 210):
        c = IOConfig(track_data_bytes=10_000_000, read_mb_s=float(mbs))
        for n in (2000, 5000):
            gains = []
            for h in (8, 9, 10, 11, 12, 13):
                lo = np.searchsorted(d["t"], S.day_start_hour(d, h))
                idx = np.arange(lo, lo + n)
                first, tracks, reqs = {}, {}, {}
                for k, i in enumerate(idx):
                    p, off, size = int(plat[i]), int(d["off"][i] % S.PLATTER_BYTES), int(d["size"][i])
                    first.setdefault(p, k)
                    reqs[p] = reqs.get(p, 0) + 1
                    tracks.setdefault(p, set()).update(range(off // c.track_data_bytes, (off + size - 1) // c.track_data_bytes + 1))
                cost = {p: c.load_mount_s + len(tracks[p]) * c.track_time() + c.unload_s for p in reqs}
                fifo = mean_completion(sorted(reqs, key=first.get), cost, reqs)
                smith = mean_completion(sorted(reqs, key=lambda p: cost[p] / reqs[p]), cost, reqs)
                gains.append((fifo, smith))
            f, s = median(g[0] for g in gains), median(g[1] for g in gains)
            print(f"{mbs:3d} MB/s N={n}: mean completion (reader only) FIFO {f/60:4.1f} min -> Smith's rule {s/60:4.1f} min ({100*(1-s/f):.0f}% lower)")
