"""Platter re-access analysis on the Fujitsu VDI trace (trace only, no simulation).

Measured in request counts, so results do not depend on any time scaling.
- popularity: how concentrated reads are on few platters
- reuse: requests and distinct other platters between two reads of the same platter
  (LRU stack distance d: an LRU cache holding C platters hits iff d < C)
- persistence: are platters hot in one window still hot in the next?
"""
import csv
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from glass_sim import vdi_workload as V
from glass_sim.io_scheduler import IOConfig

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/vdi-reuse"
OUT.mkdir(parents=True, exist_ok=True)
CACHE_SIZES = (1, 2, 4, 8, 16, 32, 64)
GAP_BINS = (1, 10, 100, 1000, 10000, 100000)
WINDOW = 2000          # requests per window for the persistence test (same size as the online experiments)
HOT_TOP = 8            # "hot" = the 8 most-read platters of a window (8 = buffer size used so far)


class Fenwick:
    def __init__(self, n):
        self.n, self.t = n, [0] * (n + 1)

    def add(self, i, v):
        i += 1
        while i <= self.n:
            self.t[i] += v
            i += i & -i

    def prefix(self, i):  # sum of [0, i)
        s = 0
        while i > 0:
            s += self.t[i]
            i -= i & -i
        return s


def stack_and_gaps(seq):
    """Per re-access: request gap and LRU stack distance (distinct other platters in between)."""
    fw, last = Fenwick(len(seq)), {}
    gaps, dists = [], []
    for i, p in enumerate(seq):
        j = last.get(p)
        if j is not None:
            gaps.append(i - j)
            dists.append(fw.prefix(i) - fw.prefix(j + 1))
            fw.add(j, -1)
        fw.add(i, 1)
        last[p] = i
    return np.array(gaps), np.array(dists)


def analyse(plat):
    n = len(plat)
    counts = np.bincount(plat)
    counts = np.sort(counts[counts > 0])[::-1]
    pop = {f"top{q}pct_platters_share": float(counts[:max(1, int(len(counts) * q / 100))].sum() / n) for q in (1, 5, 10)}
    gaps, dists = stack_and_gaps(plat.tolist())
    reaccess = len(gaps) / n
    immediate = float((dists == 0).mean())                    # same platter again with nothing in between
    lru = {f"lru_hit_C{c}": float((dists < c).sum() / n) for c in CACHE_SIZES}
    lru_beyond = {f"lru_hit_C{c}_excl_immediate": float(((dists < c) & (dists > 0)).sum() / n) for c in CACHE_SIZES}
    gap_cdf = {f"gap_le_{g}": float((gaps <= g).mean()) for g in GAP_BINS}
    # persistence: top platters of window w vs window w+1
    hits, covers = [], []
    for w in range(0, n - 2 * WINDOW, WINDOW):
        cur, nxt = plat[w:w + WINDOW], plat[w + WINDOW:w + 2 * WINDOW]
        vals, cnt = np.unique(cur, return_counts=True)
        hot = set(vals[np.argsort(cnt)[::-1][:HOT_TOP]])
        nxt_set = set(nxt.tolist())
        hits.append(len(hot & nxt_set) / len(hot))
        covers.append(np.isin(nxt, list(hot)).mean())
    return dict(requests=n, distinct_platters=int(len(counts)), reaccess_fraction=reaccess,
                immediate_repeat_of_reaccess=immediate, **pop, **gap_cdf, **lru, **lru_beyond,
                hot_still_read_next_window=float(np.median(hits)), hot_share_of_next_window=float(np.median(covers)))


def main():
    c = IOConfig()
    reads = V.load_reads(ROOT / V.TRACE)
    summary = {m: analyse(V.platter_map(reads[1], c.platters, m)) for m in V.MAPPINGS}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    with open(OUT / "summary.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["metric", *summary])
        for key in summary[V.MAPPINGS[0]]:
            w.writerow([key, *(summary[m][key] for m in summary)])
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
