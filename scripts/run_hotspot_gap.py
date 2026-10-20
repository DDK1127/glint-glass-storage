"""Hotspot gap: what short-term zone imbalance costs Zone, and how much
Silica-style work stealing recovers, at small shuttle counts.

See experiments/hotspot-gap/config.json for the registered questions.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
from dataclasses import replace
import json
from pathlib import Path
from statistics import mean, stdev
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from glass_sim.partition_feeder_study import Config, PartitionSimulation, make_moving_hotspot, make_requests


def capacity(task):
    config, count, seed = task
    metrics, _, _ = PartitionSimulation(config, make_requests(config, count, seed)).run()
    return metrics['throughput_req_s']


def simulate(task):
    config, count, seed, rate, share, dwell, variant = task
    metrics, _, _ = PartitionSimulation(config, make_moving_hotspot(config, count, seed, rate, share, dwell)).run()
    n = metrics['requests']
    return dict(shuttles=config.shuttles, hold=config.contention_hold_s, policy=config.policy, variant=variant,
                hot_share=share, dwell=dwell if dwell is not None else 'static', seed=seed, rate_req_min=60 * rate,
                p99_min=metrics['p99_s'] / 60, mean_min=metrics['mean_s'] / 60,
                helper_trips_per_req=metrics['helper_trips'] / n,
                traffic_wait_per_req_s=metrics['traffic_wait_s'] / n,
                route_motion_per_req_s=metrics['route_motion_s'] / n,
                restricted_idle_per_req_s=metrics['restricted_idle_s'] / n,
                reader_busy=metrics['reader_busy_fraction'])


def write(path, rows):
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'experiments/hotspot-gap/config.json')
    args = parser.parse_args()
    raw = json.loads(args.config.read_text(encoding='utf-8'))
    output = ROOT/raw['output_dir']
    output.mkdir(parents=True, exist_ok=True)
    base = Config(**raw['model'])
    uniform = raw['hot_shares'][0]
    workloads = [(uniform, None)] + [(s, d) for s in raw['hot_shares'][1:] for d in raw['dwells']]
    started = perf_counter()
    with ProcessPoolExecutor() as pool:
        rates = {}
        for n in raw['shuttles']:
            for hold in raw['contention_holds_s']:
                zone = replace(base, shuttles=n, buffer_slots=n * raw['buffer_per_shuttle'], policy='zone', contention_hold_s=hold)
                caps = list(pool.map(capacity, [(zone, raw['capacity_requests'], s) for s in raw['seeds']]))
                rates[(n, hold)] = raw['offered_load'] * mean(caps)
        tasks = []
        for n in raw['shuttles']:
            for hold in raw['contention_holds_s']:
                cfg = replace(base, shuttles=n, buffer_slots=n * raw['buffer_per_shuttle'], contention_hold_s=hold)
                policies = [('zone', 'zone', {})] + [('zone_ws', f'T{t}H{h}', dict(ws_threshold=t, ws_max_helpers=h))
                                                     for t, h in raw['ws_variants']]
                for share, dwell in workloads:
                    for policy, variant, extra in policies:
                        config = replace(cfg, policy=policy, **extra)
                        config.validate()
                        tasks.extend((config, raw['requests'], s, rates[(n, hold)], share, dwell, variant) for s in raw['seeds'])
        runs = list(pool.map(simulate, tasks))
    write(output/'runs.csv', runs)

    cells = {}
    for r in runs:
        cells.setdefault((r['shuttles'], r['hold'], r['policy'], r['variant'], r['hot_share'], r['dwell']), []).append(r)
    metrics = [k for k in runs[0] if k.endswith(('_min', '_s', '_req', 'busy')) and k != 'rate_req_min']
    agg = []
    for (n, hold, policy, variant, share, dwell), group in cells.items():
        row = dict(shuttles=n, hold=hold, policy=policy, variant=variant, hot_share=share, dwell=dwell,
                   runs=len(group), rate_req_min=group[0]['rate_req_min'])
        for m in metrics:
            row[m] = mean(g[m] for g in group)
        row['p99_sd'] = stdev(g['p99_min'] for g in group)
        agg.append(row)
    write(output/'aggregate.csv', agg)

    def cell(n, hold, policy, share, dwell):
        rows = [a for a in agg if a['shuttles'] == n and a['hold'] == hold and a['policy'] == policy
                and a['hot_share'] == share and (share == uniform or a['dwell'] == dwell)]
        return rows

    gap = []
    for n in raw['shuttles']:
        for hold in raw['contention_holds_s']:
            ref = cell(n, hold, 'zone', uniform, 'static')[0]
            for share in raw['hot_shares'][1:]:
                for dwell in [d if d is not None else 'static' for d in raw['dwells']]:
                    zone = cell(n, hold, 'zone', share, dwell)[0]
                    ws_rows = cell(n, hold, 'zone_ws', share, dwell)
                    best, worst = min(ws_rows, key=lambda a: a['p99_min']), max(ws_rows, key=lambda a: a['p99_min'])
                    lost = zone['p99_min'] - ref['p99_min']
                    gap.append(dict(shuttles=n, hold=hold, hot_share=share, dwell=dwell,
                                    balanced_p99=ref['p99_min'], zone_p99=zone['p99_min'],
                                    ws_best_p99=best['p99_min'], ws_best_variant=best['variant'],
                                    ws_worst_p99=worst['p99_min'], ws_worst_variant=worst['variant'],
                                    imbalance_cost_x=zone['p99_min'] / ref['p99_min'],
                                    ws_recovered_pct=100 * (zone['p99_min'] - best['p99_min']) / lost if lost > 0 else float('nan'),
                                    ws_remaining_gap_pct=100 * (best['p99_min'] - ref['p99_min']) / best['p99_min'],
                                    zone_route_s=zone['route_motion_per_req_s'], ws_route_s=best['route_motion_per_req_s'],
                                    zone_traffic_s=zone['traffic_wait_per_req_s'], ws_traffic_s=best['traffic_wait_per_req_s'],
                                    ws_helper_trips_per_req=best['helper_trips_per_req'],
                                    zone_idle_while_work_s=zone['restricted_idle_per_req_s'],
                                    ws_idle_while_work_s=best['restricted_idle_per_req_s']))
    write(output/'gap.csv', gap)
    summary = dict(config=raw, rates_req_min={f'N{n}_hold{h:g}': 60 * v for (n, h), v in rates.items()},
                   run_count=len(runs), wall_s=perf_counter() - started)
    (output/'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(f"{len(runs)} runs in {summary['wall_s']:.0f}s")


if __name__ == '__main__':
    main()
