"""Read-ahead buffer (K) and LRU platter cache (C) on the multi-LUN SYSTOR'17 traces."""
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

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "experiments/systor-cache/config.json").read_text())
OUT = ROOT / "results/systor-cache"


def windows(placement):
    d = S.load("20160222", root=ROOT / S.RAW)
    plat = S.PLACEMENTS[placement](d, IOConfig().platters, seed=CFG["seed"])
    rng = np.random.default_rng(CFG["seed"])
    sc = CFG["sampling"]
    return [S.sample(d, plat, S.day_start_hour(d, h), sc["span_s"], sc["requests"], rng) for h in sc["windows_start_hour"]]


def run(job):
    placement, w, load, scale, kind, k, cslots = job
    rel_t, plat, size = WINDOWS[placement][w]
    c = replace(IOConfig(), buffer_slots=k, cache_slots=cslots)
    s = IOSimulation(c, S.to_requests(rel_t, plat, size, scale), SilicaFIFO()).run()
    T = s["shuttle_time_s"]
    return dict(placement=placement, window=w, load=load, sweep=kind, buffer_slots=k, cache_slots=cslots,
                mean_s=s["mean_s"], p99_s=s["p99_s"], trips=s["trips"], fetch_trips=s["fetch_trips"],
                cache_hits=s["cache_hits"], evictions=s["evictions"], reader_starved=s["reader_starved_fraction"],
                shuttle_idle=T and s["shuttle_idle_s"] / T, distinct_platters=len(set(plat.tolist())))


def init(w):
    global WINDOWS
    WINDOWS = w


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    wins = {p: windows(p) for p in CFG["placements"]}
    init(wins)
    jobs = []
    for p in CFG["placements"]:
        cap = median(len(w[0]) / IOSimulation(IOConfig(), S.to_requests(*w), SilicaFIFO()).run()["makespan_s"] for w in wins[p])
        for i, (rel_t, _, _) in enumerate(wins[p]):
            for load in CFG["loads"]:
                scale = (len(rel_t) / (cap * load)) / rel_t[-1]
                jobs += [(p, i, load, scale, "k", k, CFG["k_sweep"]["cache_slots"]) for k in CFG["k_sweep"]["buffer_slots"]]
                jobs += [(p, i, load, scale, "c", CFG["c_sweep"]["buffer_slots"], c) for c in CFG["c_sweep"]["cache_slots"]]
    with ProcessPoolExecutor(8, initializer=init, initargs=(wins,)) as pool:
        rows = list(pool.map(run, jobs, chunksize=4))
    with open(OUT / "runs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    agg = []
    keys = ("mean_s", "p99_s", "trips", "fetch_trips", "cache_hits", "evictions", "reader_starved", "shuttle_idle", "distinct_platters")
    for p in CFG["placements"]:
        for load in CFG["loads"]:
            for kind, var in (("k", "buffer_slots"), ("c", "cache_slots")):
                for v in sorted({r[var] for r in rows if r["sweep"] == kind}):
                    sel = [r for r in rows if r["placement"] == p and r["load"] == load and r["sweep"] == kind and r[var] == v]
                    agg.append(dict(placement=p, load=load, sweep=kind, value=v, **{k: median(r[k] for r in sel) for k in keys}))
    with open(OUT / "aggregate.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(agg[0]))
        w.writeheader()
        w.writerows(agg)
    for a in agg:
        print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in a.items()})


if __name__ == "__main__":
    main()
