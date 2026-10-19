"""Fujitsu SYSTOR'17 VDI traces (Lee et al.): multi-LUN loading and compact caching.

Files are <YYYYMMDDHH>-LUN<k>.csv.gz with Timestamp,Response,IOType,LUN,Offset,Size.
Per the dataset README:
- the hour in the file name is JST (UTC+9); timestamps are Unix seconds;
- packets were lost for a few seconds whenever the hour changed, so the first
  SKIP_HEAD_S seconds of every hourly file are dropped;
- the LUN column inside LUN6 files may read 5, so the LUN comes from the file name;
- blank IOType rows had no response and are not reads.
Only reads are kept, cached per file as .npz (t, offset, size).
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

import numpy as np

RAW = Path("data/systor17")
CACHE = RAW / "reads_npz"
LUNS = (0, 1, 2, 3, 4, 6)
SKIP_HEAD_S = 5.0
JST = timezone(timedelta(hours=9))
NAME = re.compile(r"(\d{10})-LUN(\d)\.csv\.gz$")


def hour_start(name):
    stamp = NAME.search(name).group(1)
    return datetime.strptime(stamp, "%Y%m%d%H").replace(tzinfo=JST).timestamp()


def convert(path):
    """One hourly file -> cached reads (t, offset, size) sorted by time."""
    path = Path(path)
    out = CACHE / path.name.replace(".csv.gz", ".npz")
    if out.exists():
        return out
    # explicit dtypes: a malformed row (e.g. two timestamps fused at an hour change)
    # parses to NaN instead of turning the whole column into strings
    d = np.genfromtxt(path, delimiter=",", skip_header=1, encoding=None, usecols=(0, 2, 4, 5),
                      dtype=[("t", float), ("io", "U1"), ("off", np.float64), ("size", np.float64)])
    d = np.atleast_1d(d)
    valid = np.isfinite(d["t"]) & np.isfinite(d["off"]) & np.isfinite(d["size"])
    keep = valid & (d["io"] == "R") & (d["t"] >= hour_start(path.name) + SKIP_HEAD_S)
    r = d[keep]
    r = r[np.argsort(r["t"], kind="stable")]
    CACHE.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, t=r["t"].astype(float), off=r["off"].astype(np.int64), size=r["size"].astype(np.int64))
    return out


def files(day, hours=None, luns=LUNS, root=RAW):
    hours = hours or range(0, 24)
    return [p for h in hours for k in luns
            if (p := Path(root) / f"{day}{h:02d}-LUN{k}.csv.gz").exists()]


def convert_all(paths, workers=8):
    with ProcessPoolExecutor(workers) as pool:
        return list(pool.map(convert, paths))


def load(day, hours=None, luns=LUNS, root=RAW):
    """Reads of the given hours and LUNs merged in time: dict of arrays t, off, size, lun."""
    parts = []
    for p in files(day, hours, luns, root):
        z = np.load(convert(p))
        lun = int(NAME.search(p.name).group(2))
        parts.append((z["t"], z["off"], z["size"], np.full(len(z["t"]), lun, dtype=np.int8)))
    t, off, size, lun = (np.concatenate(x) for x in zip(*parts))
    order = np.argsort(t, kind="stable")
    return dict(t=t[order], off=off[order], size=size[order], lun=lun[order])


PLATTER_BYTES = 10**12   # 1 TB per platter (Silica: "multiple TBs", SOSP'23 §3; conservative)
EXTENT_BYTES = 2**30     # placement unit: each 1 GiB extent is written to one platter


def place(d, platters, seed=1, extent=EXTENT_BYTES, capacity=PLATTER_BYTES):
    """Random placement of (LUN, extent) onto platters, respecting platter capacity.

    The library is assumed full of other, rarely read data; the traced extents
    only take a small share of each platter, so whether two reads hit the same
    platter is decided by this random placement.
    """
    keys = d["lun"].astype(np.int64) * (1 << 40) + d["off"] // extent
    uniq, inverse = np.unique(keys, return_inverse=True)
    per_platter = capacity // extent
    if len(uniq) > platters * per_platter:
        raise ValueError("Traced data exceeds library capacity")
    rng = np.random.default_rng(seed)
    slots = rng.permutation(platters * per_platter)[:len(uniq)]   # distinct extent slots
    return (slots // per_platter)[inverse].astype(int)


def requests(d, plat, start, count, time_scale=None):
    """`count` consecutive merged reads from index `start` as simulator requests."""
    from glass_sim.io_scheduler import Request
    t, size = d["t"], d["size"]
    if start < 0 or count < 1 or start + count > len(t):
        raise ValueError("Window outside trace")
    t0 = t[start]
    return [Request(i, 0.0 if time_scale is None else float((t[start + i] - t0) * time_scale),
                    int(plat[start + i]), int(size[start + i])) for i in range(count)]


def busy_windows(d, count, windows, first_hour=8, last_hour=14):
    """Window start indices spread evenly over the busy hours [first_hour, last_hour)."""
    lo = np.searchsorted(d["t"], day_start_hour(d, first_hour))
    hi = np.searchsorted(d["t"], day_start_hour(d, last_hour)) - count - 1
    return np.linspace(lo, hi, windows).astype(int)


def day_start_hour(d, hour):
    first = datetime.fromtimestamp(d["t"][0], JST)
    return first.replace(hour=hour, minute=0, second=0, microsecond=0).timestamp()


def place_contiguous(d, platters, seed=1, capacity=PLATTER_BYTES):
    """Each LUN is written sequentially: its address space is cut into capacity-sized
    pieces, and each piece is one platter at a random rack position. The rest of the
    library holds other, rarely read data."""
    sizes = {k: int(((d["off"][d["lun"] == k] + d["size"][d["lun"] == k]).max() - 1) // capacity) + 1
             for k in np.unique(d["lun"])}
    if sum(sizes.values()) > platters:
        raise ValueError("Traced data exceeds library capacity")
    ids = np.random.default_rng(seed).permutation(platters)
    plat, base = np.empty(len(d["t"]), dtype=int), 0
    for k, n in sizes.items():
        m = d["lun"] == k
        plat[m] = ids[base + d["off"][m] // capacity]
        base += n
    return plat


PLACEMENTS = {"contig_1tb": place_contiguous, "random_1gib": place}


def sample(d, plat, start_s, span_s, count, rng):
    """`count` reads drawn uniformly (without replacement) from [start_s, start_s + span_s),
    kept in trace order. Returns (trace times relative to the first, platters, sizes)."""
    lo, hi = np.searchsorted(d["t"], [start_s, start_s + span_s])
    if hi - lo < count:
        raise ValueError("Not enough reads in the sampling span")
    idx = np.sort(rng.choice(np.arange(lo, hi), count, replace=False))
    return d["t"][idx] - d["t"][idx[0]], plat[idx], d["size"][idx]


def to_requests(rel_t, plat, size, time_scale=None):
    from glass_sim.io_scheduler import Request
    return [Request(i, 0.0 if time_scale is None else float(rel_t[i] * time_scale), int(plat[i]), int(size[i]))
            for i in range(len(rel_t))]
