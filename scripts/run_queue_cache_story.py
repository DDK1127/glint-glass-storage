"""Two-part study on real traces: the reader-front queue (Part A) and the platter cache (Part B)."""
from concurrent.futures import ProcessPoolExecutor
import csv
from dataclasses import replace
import json
from pathlib import Path
from statistics import mean, median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from glass_sim import systor17 as S
from glass_sim.io_scheduler import IOConfig, IOSimulation, SilicaFIFO

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "experiments/queue-cache-story/config.json").read_text())
OUT = ROOT / "results/queue-cache-story"
WINDOWS = {}


def init(w):
    WINDOWS.update(w)


def cfg(k, c=0):
    return replace(IOConfig(), request_overhead_s=CFG["request_overhead_s"], buffer_slots=k, cache_slots=c,
                   cache_policy=CFG["cache"]["cache_policy"])


def capacity(w):
    rel_t, plat, size = WINDOWS["w"][w]
    return len(rel_t) / IOSimulation(cfg(8), S.to_requests(rel_t, plat, size), SilicaFIFO()).run()["makespan_s"]


def run(job):
    part, w, load, rate, k, c = job
    rel_t, plat, size = WINDOWS["w"][w]
    reqs = S.to_requests(rel_t, plat, size, (len(rel_t) / rate) / rel_t[-1])
    sim = IOSimulation(cfg(k, c), reqs, SilicaFIFO())
    s = sim.run()
    shelf = [len(t["requests"]) for t in sim.trips if not t.get("from_cache")]
    cache = [len(t["requests"]) for t in sim.trips if t.get("from_cache")]
    return dict(part=part, window=w, load=load, rate_req_s=rate, queue_slots=k, cache_slots=c,
                mean_s=s["mean_s"], p99_s=s["p99_s"], opens=len(sim.trips), fetch_trips=s["fetch_trips"],
                requests_per_open=len(reqs) / len(sim.trips), reader_busy=s["reader_busy_fraction"],
                reader_waiting=s["reader_starved_fraction"],
                shuttle_wait_at_reader=s["gate_wait_s"] / s["shuttle_time_s"],
                shelf_opens=len(shelf), shelf_requests_per_open=mean(shelf) if shelf else 0.0,
                cache_opens=len(cache), cache_requests_per_open=mean(cache) if cache else 0.0,
                cache_opens_le2=(sum(n <= 2 for n in cache) / len(cache)) if cache else 0.0,
                shelf_opens_le2=(sum(n <= 2 for n in shelf) / len(shelf)) if shelf else 0.0)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    d = S.load("20160222", root=ROOT / S.RAW)
    plat = S.PLACEMENTS[CFG["placement"]](d, IOConfig().platters, seed=CFG["seed"])
    rng = np.random.default_rng(CFG["seed"])
    sc = CFG["sampling"]
    wins = {"w": [S.sample(d, plat, S.day_start_hour(d, h), sc["span_s"], sc["requests"], rng) for h in sc["windows_start_hour"]]}
    init(wins)
    n = len(wins["w"])
    with ProcessPoolExecutor(8, initializer=init, initargs=(wins,)) as pool:
        cap = median(pool.map(capacity, range(n)))
        jobs = []
        for load, m in CFG["loads"].items():
            for w in range(n):
                jobs += [("A", w, load, m * cap, k, 0) for k in CFG["queue_slots"]]
                jobs += [("B", w, load, m * cap, CFG["cache"]["buffer_slots"], c) for c in (0, CFG["cache"]["cache_slots"])]
        rows = list(pool.map(run, jobs, chunksize=2))
    with open(OUT / "runs.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    keys = [k for k in rows[0] if k not in ("part", "window", "load", "queue_slots", "cache_slots")]
    agg = []
    for part in ("A", "B"):
        for load in CFG["loads"]:
            for k, c in sorted({(r["queue_slots"], r["cache_slots"]) for r in rows if r["part"] == part}):
                sel = [r for r in rows if r["part"] == part and r["load"] == load and (r["queue_slots"], r["cache_slots"]) == (k, c)]
                agg.append(dict(part=part, load=load, queue_slots=k, cache_slots=c, **{x: median(r[x] for r in sel) for x in keys}))
    with open(OUT / "aggregate.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(agg[0]))
        wr.writeheader()
        wr.writerows(agg)
    for a in agg:
        print(a["part"], a["load"], f"K={a['queue_slots']:2d} C={a['cache_slots']}", f"p99 {a['p99_s']:5.0f} mean {a['mean_s']:4.0f}",
              f"reader waiting {a['reader_waiting']:.0%} busy {a['reader_busy']:.0%} shuttle@reader {a['shuttle_wait_at_reader']:.0%}",
              f"opens {a['opens']:.0f} req/open {a['requests_per_open']:.1f} | shelf {a['shelf_opens']:.0f}x{a['shelf_requests_per_open']:.1f} (<=2: {a['shelf_opens_le2']:.0%})",
              f"cache {a['cache_opens']:.0f}x{a['cache_requests_per_open']:.1f} (<=2: {a['cache_opens_le2']:.0%})")


if __name__ == "__main__":
    main()
