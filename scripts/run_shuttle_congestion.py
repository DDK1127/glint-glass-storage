"""Shuttle-count sweep under a simple congestion (stop-and-go) model.

Same fixed partition as run_shuttle_provisioning.py. `contention_hold_s` adds one
stop-and-go per vehicle that blocks a route step, and that time occupies the
contested block (see Rail.estimate). Each hold value is a sensitivity level, not
a calibrated constant; hold=0 reproduces the free-flow provisioning sweep.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
from statistics import mean, stdev
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from glass_sim.partition_feeder_study import Config, PartitionSimulation, make_requests

INK, MUTED = '#21352E', '#5F7069'
HOLD_COLORS = ['#A9C2B3', '#2B4A3C']  # free flow (light) vs congested (dark)
STATE_COLORS = {'moving': '#547465', 'traffic_wait': '#B55757', 'reader_wait': '#DDB264',
                'handling': '#93AD9C', 'idle': '#DFE7E2'}
STATE_LABELS = {'moving': 'Moving (incl. stop-and-go)', 'traffic_wait': 'Waiting for other shuttles',
                'reader_wait': 'Queued at reader gate', 'handling': 'Pick / place / handoff', 'idle': 'Idle (no work)'}
PHASE_STATE = {'fetch': 'moving', 'delivery': 'moving', 'to_output': 'moving', 'return': 'moving',
               'traffic_wait': 'traffic_wait', 'delivery_wait': 'reader_wait', 'output_pick_wait': 'reader_wait',
               'pick': 'handling', 'place': 'handling', 'handoff': 'handling', 'output_pick': 'handling'}


def simulate(task):
    config, count, seed, pattern = task
    metrics, _, timeline = PartitionSimulation(config, make_requests(config, count, seed, pattern)).run()
    span = metrics['drain_span_s']
    states = dict.fromkeys(STATE_COLORS, 0.0)
    for row in timeline:
        if row['resource'].startswith('S') and row['phase'] in PHASE_STATE:
            states[PHASE_STATE[row['phase']]] += row['end_s'] - row['start_s']
    states['idle'] = config.shuttles * span - sum(states.values())
    # Time-averaged number of shuttles in each state over the whole run.
    shares = {f'avg_shuttles_{k}': v / span for k, v in states.items()}
    return dict(seed=seed, shuttles=config.shuttles, contention_hold_s=config.contention_hold_s, **metrics, **shares)


def aggregate(runs, holds, shuttle_counts):
    rows = []
    for hold in holds:
        for n in shuttle_counts:
            group = [r for r in runs if r['shuttles'] == n and r['contention_hold_s'] == hold]
            item = {'contention_hold_s': hold, 'shuttles': n, 'runs': len(group)}
            for key, value in group[0].items():
                if key in {'seed', 'shuttles', 'contention_hold_s', 'workload_sha256'} or not isinstance(value, (int, float)):
                    continue
                values = [r[key] for r in group]
                item[key+'_mean'] = mean(values)
                item[key+'_sd'] = stdev(values) if len(values) > 1 else 0.0
            item['throughput_req_min'] = 60 * item['throughput_req_s_mean']
            item['throughput_req_min_sd'] = 60 * item['throughput_req_s_sd']
            item['p99_min'] = item['p99_s_mean'] / 60
            rows.append(item)
    return rows


def plot(rows, holds, raw, output):
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT/'results/.mplconfig'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size': 11, 'axes.edgecolor': '#BBC8C0', 'axes.labelcolor': INK,
                         'xtick.color': MUTED, 'ytick.color': MUTED})
    subtitle = (f"1 reader · 8 rows · {raw['length_m']:g} m · read={raw['read_s']:g} s · B={raw['buffer_slots']} · "
                f"Non-Zone FIFO · {len(raw['seeds'])} seeds × {raw['requests']} requests")
    x = sorted({r['shuttles'] for r in rows})

    # Figure 1: throughput vs N, one line per stop-and-go cost, peak marked.
    fig, ax = plt.subplots(figsize=(8.6, 4.8))
    for hold, color in zip(holds, HOLD_COLORS):
        group = sorted((r for r in rows if r['contention_hold_s'] == hold), key=lambda r: r['shuttles'])
        y = [r['throughput_req_min'] for r in group]
        ax.errorbar(x, y, yerr=[r['throughput_req_min_sd'] for r in group], marker='o', markersize=6, capsize=2,
                    linewidth=2, color=color, label='With congestion' if hold else 'No congestion')
        peak = max(group, key=lambda r: r['throughput_req_min'])
        if hold:
            ax.annotate(f"peak N={peak['shuttles']}", (peak['shuttles'], peak['throughput_req_min']),
                        xytext=(0, 12), textcoords='offset points', ha='center', fontsize=9, color=INK,
                        bbox=dict(boxstyle='round,pad=0.15', fc='white', ec='none', alpha=.85))
    ax.set(xscale='log', xticks=x, xticklabels=[str(v) for v in x], ylim=(0, None),
           xlabel='Shuttles per partition (1 reader)', ylabel='Read completions / min')
    ax.minorticks_off()
    ax.tick_params(axis='x', labelsize=9)
    ax.spines[['top', 'right']].set_visible(False)
    ax.legend(frameon=False, loc='upper left', fontsize=10.5)
    ax.set_title(subtitle, fontsize=9.5, color=MUTED)
    fig.tight_layout()
    fig.savefig(output/'fig_congestion_throughput.png', dpi=190)
    plt.close(fig)

    # Figure 2: where the shuttles' time goes, at the focus hold.
    focus = float(raw['focus_hold_s'])
    shown = raw['breakdown_shuttles']
    group = {r['shuttles']: r for r in rows if r['contention_hold_s'] == focus}
    fig, ax = plt.subplots(figsize=(8.6, 4.8))
    bottom = [0.0] * len(shown)
    labels = [str(n) for n in shown]
    for state, color in STATE_COLORS.items():
        values = [100 * group[n][f'avg_shuttles_{state}_mean'] / n for n in shown]
        ax.bar(labels, values, bottom=bottom, color=color, edgecolor='white', linewidth=1.5, label=STATE_LABELS[state], width=.62)
        if state == 'traffic_wait':
            for i, v in enumerate(values):
                if v >= 8:
                    ax.text(i, bottom[i] + v/2, f'{v:.0f}%', ha='center', va='center', fontsize=9.5, color='white', fontweight='bold')
        bottom = [b + v for b, v in zip(bottom, values)]
    ax.set(ylim=(0, 100), xlabel='Shuttles per partition', ylabel='Share of shuttle time (%)')
    ax.spines[['top', 'right']].set_visible(False)
    ax.legend(frameon=False, loc='center left', bbox_to_anchor=(1.0, .5), fontsize=9.5)
    ax.set_title(f'With congestion · 1 reader · {raw["length_m"]:g} m · read={raw["read_s"]:g} s · B={raw["buffer_slots"]}',
                 fontsize=9.5, color=MUTED)
    fig.tight_layout()
    fig.savefig(output/'fig_congestion_breakdown.png', dpi=190)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'experiments/partition-feeder-story/shuttle-congestion.json')
    args = parser.parse_args()
    raw = json.loads(args.config.read_text(encoding='utf-8'))
    output = ROOT/raw['output_dir']
    output.mkdir(parents=True, exist_ok=True)
    holds = [float(h) for h in raw['contention_holds_s']]
    shuttle_counts = sorted(raw['shuttles'])
    base = replace(Config(**raw['model']), length_m=float(raw['length_m']), read_s=float(raw['read_s']),
                   buffer_slots=raw['buffer_slots'], policy=raw['policy'])
    tasks = []
    for hold in holds:
        for n in shuttle_counts:
            config = replace(base, shuttles=n, contention_hold_s=hold)
            config.validate()
            tasks.extend((config, raw['requests'], seed, raw['pattern']) for seed in raw['seeds'])
    started = perf_counter()
    with ProcessPoolExecutor() as pool:
        runs = list(pool.map(simulate, tasks))
    rows = aggregate(runs, holds, shuttle_counts)
    with (output/'runs.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(runs[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(runs)
    with (output/'aggregate.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    peaks = {}
    for hold in holds:
        group = [r for r in rows if r['contention_hold_s'] == hold]
        peak = max(group, key=lambda r: r['throughput_req_min'])
        last = max(group, key=lambda r: r['shuttles'])
        peaks[str(hold)] = {'peak_shuttles': peak['shuttles'], 'peak_throughput_req_min': peak['throughput_req_min'],
                            'peak_reader_busy': peak['reader_busy_fraction_mean'],
                            'n_max': last['shuttles'], 'n_max_throughput_req_min': last['throughput_req_min'],
                            'n_max_avg_shuttles_traffic_wait': last['avg_shuttles_traffic_wait_mean']}
    summary = {'config': raw, 'effective_common': asdict(base), 'run_count': len(runs), 'peaks_by_hold': peaks,
               'model': 'contention_hold_s per blocking reservation, added to the contested block occupancy',
               'wall_s': perf_counter() - started}
    (output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    plot(rows, holds, raw, output)
    print(json.dumps(peaks, indent=2))


if __name__ == '__main__':
    main()
