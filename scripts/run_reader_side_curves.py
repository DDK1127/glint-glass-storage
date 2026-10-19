"""Latency-load curves for the read-ahead baseline, LRU and GreedyDual-Size platter caches."""
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
CFG = json.loads((ROOT / "experiments/reader-side-curves/config.json").read_text())
OUT = ROOT / "results/reader-side-curves"
WINDOWS = {}


def init(w):
    WINDOWS.update(w)


def config(overhead, variant):
    return replace(IOConfig(), request_overhead_s=overhead, **CFG["variants"][variant])


def capacity(job):
    w, overhead = job
    rel_t, plat, size = WINDOWS["w"][w]
    return job, len(rel_t) / IOSimulation(config(overhead, "baseline"), S.to_requests(rel_t, plat, size), SilicaFIFO()).run()["makespan_s"]


def run(job):
    w, overhead, mult, rate, variant = job
    rel_t, plat, size = WINDOWS["w"][w]
    c = config(overhead, variant)
    reqs = S.to_requests(rel_t, plat, size, (len(rel_t) / rate) / rel_t[-1])
    sim = IOSimulation(c, reqs, SilicaFIFO())
    s = sim.run()
    trips = sorted(sim.trips, key=lambda t: t["read_start_s"])
    gaps, last = [], {}
    for t in trips:   # G2: time from a platter's last read to its next opening request
        first = min(reqs[i].arrival_s for i in t["requests"])
        if t["platter"] in last:
            gaps.append(max(0.0, first - last[t["platter"]]))
        last[t["platter"]] = t["read_done_s"]
    makespan = s["makespan_s"]
    return dict(window=w, overhead_s=overhead, load_mult=mult, rate_req_s=rate, variant=variant,
                mean_s=s["mean_s"], p99_s=s["p99_s"], opens=len(trips), fetch_trips=s["fetch_trips"],
                requests_per_open=len(reqs) / len(trips), cache_hits=s["cache_hits"], evictions=s["evictions"],
                reader_busy=s["reader_busy_fraction"], reader_blocked=s["reader_blocked_s"] / makespan,
                fetch_travel_s=sum(2 * sim.fetch_cost(t["platter"]) for t in trips if not t.get("from_cache")),
                reopen_30s=float(np.mean([g <= 30 for g in gaps])) if gaps else 0.0), gaps


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
        caps = dict(pool.map(capacity, [(w, o) for w in range(n) for o in CFG["request_overhead_s"]]))
        jobs = [(w, o, m, m * median(caps[(x, o)] for x in range(n)), v)
                for o in CFG["request_overhead_s"] for m in CFG["load_multipliers"] for w in range(n) for v in CFG["variants"]]
        out = list(pool.map(run, jobs, chunksize=2))
    rows = [r for r, _ in out]
    with open(OUT / "runs.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    with open(OUT / "reopen_gaps_baseline.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["overhead_s", "load_mult", "window", "gap_s"])
        for (r, gaps) in out:
            if r["variant"] == "baseline":
                wr.writerows([r["overhead_s"], r["load_mult"], r["window"], g] for g in gaps)
    keys = [k for k in rows[0] if k not in ("window", "overhead_s", "load_mult", "variant")]
    agg = []
    for o in CFG["request_overhead_s"]:
        for m in CFG["load_multipliers"]:
            for v in CFG["variants"]:
                sel = [r for r in rows if r["overhead_s"] == o and r["load_mult"] == m and r["variant"] == v]
                agg.append(dict(overhead_s=o, load_mult=m, variant=v, **{k: median(r[k] for r in sel) for k in keys}))
    with open(OUT / "aggregate.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(agg[0]))
        wr.writeheader()
        wr.writerows(agg)
    for a in agg:
        print(a["overhead_s"], a["load_mult"], f"{a['variant']:10s} rate {a['rate_req_s']:.3f} mean {a['mean_s']:6.0f} p99 {a['p99_s']:6.0f}",
              f"opens {a['opens']:4.0f} fetch {a['fetch_trips']:4.0f} req/open {a['requests_per_open']:5.1f} busy {a['reader_busy']:.0%}",
              f"blocked {a['reader_blocked']:.1%} travel {a['fetch_travel_s']/60:5.0f}min reopen30 {a['reopen_30s']:.0%}")


if __name__ == "__main__":
    main()
