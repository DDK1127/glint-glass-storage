"""Reader-side observations: what the FIFO buffer and an LRU platter cache ignore about glass.

G1 fixed cost per platter opening -> requests per opening, mount/unload share of reader time
G2 hour-scale SLO -> requests that arrive just after their platter was put away
G3 location-dependent fetch cost -> how much the cost of a miss varies (LRU ignores it)
G4 an eviction is a shuttle trip -> evictions and return trips
G5 shared space near the reader -> splitting a fixed slot budget between buffer and cache
"""
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
from glass_sim.partition_feeder_study import Rail

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "experiments/reader-side-obs/config.json").read_text())
OUT = ROOT / "results/reader-side-obs"
WINDOWS = {}


def init(w):
    WINDOWS.update(w)


def one_way(c, platter):
    return sum(d for _, d in Rail(c).path(Rail.READER, c.home(platter)))


def analyse(c, reqs, sim, s):
    """Per-run metrics for G1-G4."""
    trips = sorted(sim.trips, key=lambda t: t["read_start_s"])
    opens = len(trips)
    mount = opens * (c.load_mount_s + c.unload_s)
    reads = sum(c.read_time(r.size_bytes) for r in reqs)
    row = dict(opens=opens, requests_per_open=len(reqs) / opens, mount_share_of_reader_work=mount / (mount + reads),
               fetch_trips=s["fetch_trips"], cache_hits=s["cache_hits"], evictions=s["evictions"],
               mean_s=s["mean_s"], p99_s=s["p99_s"], reader_busy=s["reader_busy_fraction"],
               reader_starved=s["reader_starved_fraction"])
    # G2: openings of a platter that start soon after the same platter finished reading
    last_done = {}
    for t in trips:
        first_arrival = min(reqs[i].arrival_s for i in t["requests"])
        prev = last_done.get(t["platter"])
        for w in CFG["g2_wait_windows_s"]:
            row[f"reopen_within_{w}s"] = row.get(f"reopen_within_{w}s", 0) + (prev is not None and first_arrival - prev <= w)
        last_done[t["platter"]] = t["read_done_s"]
    for w in CFG["g2_wait_windows_s"]:
        row[f"reopen_within_{w}s"] /= opens
    # G3: spread of one-way fetch time over the platters actually fetched
    cost = [one_way(c, t["platter"]) for t in trips if not t.get("from_cache")]
    if cost:
        row.update(fetch_one_way_min_s=min(cost), fetch_one_way_median_s=median(cost), fetch_one_way_max_s=max(cost))
    return row


def run(job):
    w, overhead, k, cslots, scale, tag = job
    rel_t, plat, size = WINDOWS["w"][w]
    c = replace(IOConfig(), request_overhead_s=overhead, buffer_slots=k, cache_slots=cslots)
    reqs = S.to_requests(rel_t, plat, size, scale)
    sim = IOSimulation(c, reqs, SilicaFIFO())
    s = sim.run()
    row = dict(tag=tag, window=w, overhead_s=overhead, buffer_slots=k, cache_slots=cslots, **analyse(c, reqs, sim, s))
    return row


def capacity(job):
    w, overhead = job
    rel_t, plat, size = WINDOWS["w"][w]
    c = replace(IOConfig(), request_overhead_s=overhead)
    return job, len(rel_t) / IOSimulation(c, S.to_requests(rel_t, plat, size), SilicaFIFO()).run()["makespan_s"]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    d = S.load("20160222", root=ROOT / S.RAW)
    plat = S.PLACEMENTS[CFG["placement"].split(":")[0]](d, IOConfig().platters, seed=CFG["seed"])
    rng = np.random.default_rng(CFG["seed"])
    sc = CFG["sampling"]
    wins = {"w": [S.sample(d, plat, S.day_start_hour(d, h), sc["span_s"], sc["requests"], rng) for h in sc["windows_start_hour"]]}
    init(wins)
    n = len(wins["w"])
    with ProcessPoolExecutor(8, initializer=init, initargs=(wins,)) as pool:
        caps = dict(pool.map(capacity, [(w, o) for w in range(n) for o in CFG["request_overhead_s"]]))
        jobs = []
        for o in CFG["request_overhead_s"]:
            cap = median(caps[(w, o)] for w in range(n))
            for w in range(n):
                scale = (sc["requests"] / (cap * CFG["load"])) / wins["w"][w][0][-1]
                jobs += [(w, o, 8, cs, scale, "g1") for cs in CFG["g1_cache_slots"]]
                jobs += [(w, o, k, cs, scale, "g5") for k, cs in CFG["g5_budget"]["splits_buffer_cache"]]
        rows = list(pool.map(run, jobs, chunksize=2))
    keys = sorted({k for r in rows for k in r})
    with open(OUT / "runs.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=keys)
        wr.writeheader()
        wr.writerows(rows)
    agg = []
    for tag in ("g1", "g5"):
        for o in CFG["request_overhead_s"]:
            combos = sorted({(r["buffer_slots"], r["cache_slots"]) for r in rows if r["tag"] == tag}, key=lambda x: (-x[0], x[1]))
            for k, cs in combos:
                sel = [r for r in rows if r["tag"] == tag and r["overhead_s"] == o and (r["buffer_slots"], r["cache_slots"]) == (k, cs)]
                num = [x for x in sel[0] if isinstance(sel[0][x], (int, float)) and x not in ("window", "overhead_s", "buffer_slots", "cache_slots")]
                agg.append(dict(tag=tag, overhead_s=o, buffer_slots=k, cache_slots=cs,
                                **{x: median(r[x] for r in sel if x in r) for x in num}))
    keys = sorted({k for a in agg for k in a}, key=lambda x: (x not in ("tag", "overhead_s", "buffer_slots", "cache_slots"), x))
    with open(OUT / "aggregate.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=keys)
        wr.writeheader()
        wr.writerows(agg)
    for a in agg:
        print(a["tag"], a["overhead_s"], f"K={a['buffer_slots']} C={a['cache_slots']}",
              f"p99 {a['p99_s']:.0f} mean {a['mean_s']:.0f} opens {a['opens']:.0f} req/open {a['requests_per_open']:.2f}",
              f"mount {a['mount_share_of_reader_work']:.0%} busy {a['reader_busy']:.0%} fetch {a['fetch_trips']:.0f} evict {a['evictions']:.0f}",
              "reopen<=30/60/300s", f"{a['reopen_within_30s']:.0%}/{a['reopen_within_60s']:.0%}/{a['reopen_within_300s']:.0%}",
              f"fetch one-way {a.get('fetch_one_way_min_s', 0):.0f}-{a.get('fetch_one_way_max_s', 0):.0f}s")


if __name__ == "__main__":
    main()
