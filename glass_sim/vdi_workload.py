"""Fujitsu enterprise VDI block trace (Lee et al., SYSTOR'17) as glass-library read requests.

The trace has no platter locations, so the mapping from logical address to
platter is an explicit, reported choice. Arrival order and request sizes are
taken from the trace unchanged; only the time axis may be compressed or
stretched (time_scale), because a glass library serves far fewer reads per
second than the VDI primary storage that produced the trace.
"""
from __future__ import annotations

import random

import numpy as np

from glass_sim.io_scheduler import Request

TRACE = "data/2016022211-LUN0.csv"
MAPPINGS = ("contiguous", "hash_1gib")


def load_reads(path=TRACE):
    """Read requests sorted by timestamp: arrays (t_s, offset, size)."""
    d = np.genfromtxt(path, delimiter=",", skip_header=1, dtype=None, encoding=None,
                      usecols=(0, 2, 4, 5), names=("t", "io", "off", "size"))
    r = d[d["io"] == "R"]
    r = r[np.argsort(r["t"], kind="stable")]
    return r["t"].astype(float), r["off"].astype(np.int64), r["size"].astype(np.int64)


def platter_map(offsets, platters, mapping, seed=1):
    """contiguous: the observed address range is split evenly over the platters in
    rack order. hash_1gib: each 1 GiB extent goes to a seeded random platter."""
    if mapping == "contiguous":
        lo, hi = int(offsets.min()), int(offsets.max()) + 1
        return ((offsets - lo) * platters // (hi - lo)).astype(int)
    if mapping == "hash_1gib":
        extents, inverse = np.unique(offsets // 2**30, return_inverse=True)
        rng = random.Random(seed)
        return np.array([rng.randrange(platters) for _ in extents])[inverse]
    raise ValueError(f"Unknown mapping {mapping}")


def requests(reads, plat, start, count, time_scale=None):
    """`count` consecutive trace reads from index `start`.

    time_scale=None: all arrive at t=0 (one burst, order preserved).
    time_scale=k: arrival = (t - t_start) * k, keeping the trace's burst shape.
    """
    t, _, size = reads
    if start < 0 or count < 1 or start + count > len(t):
        raise ValueError("Window outside trace")
    t0 = t[start]
    return [Request(i, 0.0 if time_scale is None else float((t[start + i] - t0) * time_scale),
                    int(plat[start + i]), int(size[start + i])) for i in range(count)]
