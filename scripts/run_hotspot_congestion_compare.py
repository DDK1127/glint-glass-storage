"""Same scenario as results/hotspot-gap, adding Non-Zone FIFO and conflict metrics.

How severe are shuttle conflicts when every shuttle may serve any row, compared
with Zone and Zone + work stealing? Reuses the arrival rates in
results/hotspot-gap/summary.json so all three policies see identical requests.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import csv
from dataclasses import replace
import json
from pathlib import Path
from statistics import mean, stdev
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from glass_sim.partition_feeder_study import Config, PartitionSimulation, make_moving_hotspot

OUT = ROOT/'results/hotspot-gap'
HOLD, REQUESTS, SEEDS = 0.5, 2400, [101, 202, 303, 404, 505]
WORKLOADS = [(0.125, None), (0.47, 100)]


def best_ws_variants():
    best = {}
    for r in csv.DictReader((OUT/'gap.csv').open(encoding='utf-8')):
        if float(r['hold']) == HOLD and float(r['hot_share']) == 0.47 and r['dwell'] == '100':
            t, h = r['ws_best_variant'][1:].split('H')
            best[int(r['shuttles'])] = (int(t), int(h))
    return best


def simulate(task):
    config, rate, share, dwell, seed = task
    metrics, _, timeline = PartitionSimulation(config, make_moving_hotspot(config, REQUESTS, seed, rate, share, dwell)).run()
    n, span = metrics['requests'], metrics['drain_span_s']
    waiting = sum(r['end_s'] - r['start_s'] for r in timeline if r['resource'].startswith('S') and r['phase'] == 'traffic_wait')
    return dict(shuttles=config.shuttles, policy=config.policy, hot_share=share, dwell=dwell or 'static', seed=seed,
                p99_min=metrics['p99_s'] / 60, mean_min=metrics['mean_s'] / 60,
                conflicts_per_req=metrics['contended_steps'] / n,
                traffic_wait_per_req_s=metrics['traffic_wait_s'] / n,
                shuttle_time_waiting_pct=100 * waiting / (config.shuttles * span),
                route_motion_per_req_s=metrics['route_motion_s'] / n,
                throughput_req_min=60 * metrics['throughput_req_s'])


def main():
    rates = json.loads((OUT/'summary.json').read_text())['rates_req_min']
    ws = best_ws_variants()
    tasks = []
    for n in (2, 4, 8):
        base = Config(shuttles=n, buffer_slots=n, docking_bays=32, length_m=32.0, read_s=8.0, contention_hold_s=HOLD)
        rate = rates[f'N{n}_hold{HOLD:g}'] / 60
        policies = [replace(base, policy='zone'), replace(base, policy='zone_ws', ws_threshold=ws[n][0], ws_max_helpers=ws[n][1]),
                    replace(base, policy='nonzone_fifo')]
        for config in policies:
            for share, dwell in WORKLOADS:
                tasks.extend((config, rate, share, dwell, s) for s in SEEDS)
    with ProcessPoolExecutor() as pool:
        runs = list(pool.map(simulate, tasks))
    keys = [k for k in runs[0] if k not in ('shuttles', 'policy', 'hot_share', 'dwell', 'seed')]
    agg = []
    for n in (2, 4, 8):
        for policy in ('zone', 'zone_ws', 'nonzone_fifo'):
            for share, dwell in WORKLOADS:
                g = [r for r in runs if r['shuttles'] == n and r['policy'] == policy and r['hot_share'] == share and r['dwell'] == (dwell or 'static')]
                row = dict(shuttles=n, policy=policy, hot_share=share, dwell=dwell or 'static', runs=len(g))
                for k in keys:
                    row[k] = mean(x[k] for x in g)
                row['p99_sd'] = stdev(x['p99_min'] for x in g)
                agg.append(row)
    for name, rows in (('compare_runs.csv', runs), ('compare_aggregate.csv', agg)):
        with (OUT/name).open('w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)
    for r in agg:
        print(f"N{r['shuttles']} {r['policy']:<12} share={r['hot_share']:<5} p99={r['p99_min']:7.1f} conflicts/req={r['conflicts_per_req']:6.2f} "
              f"wait/req={r['traffic_wait_per_req_s']:7.1f}s waiting={r['shuttle_time_waiting_pct']:5.1f}% thr={r['throughput_req_min']:.2f}")


if __name__ == '__main__':
    main()
