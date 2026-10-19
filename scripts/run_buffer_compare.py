"""Does a larger prefetch buffer help Zone, Zone + work stealing or Non-Zone?

Same hotspot scenario as results/hotspot-gap (N=8, congestion cost 0.5 s,
identical requests and arrival rate); only the feeder-buffer capacity B varies.
Also records how busy the reader entrance and each connector are, to locate
where shuttles actually queue.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import csv
from dataclasses import replace
import json
from pathlib import Path
from statistics import mean
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from glass_sim.partition_feeder_study import Config, PartitionSimulation, make_moving_hotspot

OUT = ROOT/'results/hotspot-gap'
N, HOLD, REQUESTS, SEEDS = 8, 0.5, 2400, [101, 202, 303, 404, 505]
BUFFERS = [0, 4, 8, 16]
WORKLOADS = [(0.125, None), (0.47, 100)]
POLICIES = [('zone', {}), ('zone_ws', dict(ws_threshold=4, ws_max_helpers=1)), ('nonzone_fifo', {})]


def simulate(task):
    config, rate, share, dwell, seed = task
    sim = PartitionSimulation(config, make_moving_hotspot(config, REQUESTS, seed, rate, share, dwell))
    metrics, _, timeline = sim.run()
    n, span = metrics['requests'], metrics['drain_span_s']
    busy = {}
    for rec in sim.rail.records:
        busy[rec['resource']] = busy.get(rec['resource'], 0.0) + rec['end_s'] - rec['start_s']
    connectors = [v / span for k, v in busy.items() if k.startswith('connector')]
    waiting = sum(r['end_s'] - r['start_s'] for r in timeline if r['resource'].startswith('S') and r['phase'] == 'traffic_wait')
    return dict(policy=config.policy, buffer=config.buffer_slots, hot_share=share, seed=seed,
                p99_min=metrics['p99_s'] / 60, mean_min=metrics['mean_s'] / 60,
                throughput_req_min=60 * metrics['throughput_req_s'],
                traffic_wait_per_req_s=metrics['traffic_wait_s'] / n,
                delivery_wait_per_req_s=metrics['delivery_wait_s'] / n,
                shuttle_time_waiting_pct=100 * waiting / (config.shuttles * span),
                reader_entrance_busy_pct=100 * busy.get('reader_approach', 0.0) / span,
                busiest_connector_busy_pct=100 * max(connectors) if connectors else 0.0,
                reader_busy_pct=100 * metrics['reader_busy_fraction'])


def main():
    rate = json.loads((OUT/'summary.json').read_text())['rates_req_min'][f'N{N}_hold{HOLD:g}'] / 60
    tasks = []
    for policy, extra in POLICIES:
        for b in BUFFERS:
            config = replace(Config(shuttles=N, buffer_slots=b, docking_bays=32, length_m=32.0, read_s=8.0,
                                    contention_hold_s=HOLD, policy=policy), **extra)
            config.validate()
            for share, dwell in WORKLOADS:
                tasks.extend((config, rate, share, dwell, s) for s in SEEDS)
    with ProcessPoolExecutor() as pool:
        runs = list(pool.map(simulate, tasks))
    keys = [k for k in runs[0] if k not in ('policy', 'buffer', 'hot_share', 'seed')]
    agg = []
    for policy, _ in POLICIES:
        for b in BUFFERS:
            for share, _ in WORKLOADS:
                g = [r for r in runs if r['policy'] == policy and r['buffer'] == b and r['hot_share'] == share]
                agg.append(dict(policy=policy, buffer=b, hot_share=share, runs=len(g), **{k: mean(x[k] for x in g) for k in keys}))
    for name, rows in (('buffer_runs.csv', runs), ('buffer_aggregate.csv', agg)):
        with (OUT/name).open('w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)
    for r in agg:
        print(f"{r['policy']:<12} B={r['buffer']:<2} share={r['hot_share']:<5} p99={r['p99_min']:7.1f} thr={r['throughput_req_min']:.2f} "
              f"trafficwait={r['traffic_wait_per_req_s']:6.1f}s deliverywait={r['delivery_wait_per_req_s']:5.1f}s waiting={r['shuttle_time_waiting_pct']:5.1f}% "
              f"entrance={r['reader_entrance_busy_pct']:5.1f}% connector={r['busiest_connector_busy_pct']:5.1f}% reader={r['reader_busy_pct']:5.1f}%")


if __name__ == '__main__':
    main()
