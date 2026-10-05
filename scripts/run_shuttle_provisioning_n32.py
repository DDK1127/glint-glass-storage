"""Focused shuttle-count sweep for slide 6: one partition, one reader."""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
import json
from pathlib import Path
from statistics import mean, stdev
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from glass_sim.partition_feeder_study import Config, PartitionSimulation, make_requests


def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'experiments/partition-feeder-story/shuttle-provisioning-n32.json')
    args = parser.parse_args()
    raw = json.loads(args.config.read_text(encoding='utf-8'))
    base = Config(**raw['model'])
    output = ROOT/raw['output_dir']
    output.mkdir(parents=True, exist_ok=True)
    runs = []
    started = perf_counter()
    penalties = raw.get('yield_penalties_s', [0.0])
    for seed in raw['seeds']:
        for shuttle_count in raw['shuttles']:
            for penalty in penalties:
                config = replace(base, shuttles=shuttle_count, length_m=raw['length_m'], read_s=raw['read_s'],
                                 buffer_slots=raw['buffer_slots'], policy=raw['policy'], yield_penalty_s=float(penalty))
                config.validate()
                requests = make_requests(config, raw['requests'], seed, raw['pattern'])
                metrics, _, _ = PartitionSimulation(config, requests).run()
                runs.append(dict(seed=seed, shuttles=shuttle_count, yield_penalty_s=float(penalty), **metrics))
    aggregates = []
    for penalty in penalties:
        for shuttle_count in raw['shuttles']:
            group = [row for row in runs if row['shuttles'] == shuttle_count and row['yield_penalty_s'] == float(penalty)]
            item = {'shuttles': shuttle_count, 'yield_penalty_s': float(penalty), 'runs': len(group)}
            for key, value in group[0].items():
                if key in {'seed', 'shuttles', 'yield_penalty_s', 'workload_sha256'} or not isinstance(value, (int, float)):
                    continue
                values = [row[key] for row in group]
                item[key+'_mean'] = mean(values)
                item[key+'_sd'] = stdev(values) if len(values)>1 else 0.0
            aggregates.append(item)
    write_csv(output/'runs.csv', runs)
    write_csv(output/'aggregate.csv', aggregates)
    target = {str(penalty): next((row['shuttles'] for row in aggregates if row['yield_penalty_s'] == float(penalty) and row['reader_busy_fraction_mean'] >= .90), None) for penalty in penalties}
    summary = {'config': raw, 'effective_common': asdict(replace(base, length_m=raw['length_m'], read_s=raw['read_s'], buffer_slots=raw['buffer_slots'], policy=raw['policy'], yield_penalty_s=float(penalties[0]))), 'run_count': len(runs),
               'selection_rule': 'smallest N with mean reader busy fraction >= 0.90, reported per yield penalty',
               'selected_shuttles_by_penalty': target, 'wall_s': perf_counter()-started,
               'collision_interpretation': 'collisions are prevented; traffic_wait_s includes safe reservation waiting and controlled yield penalty'}
    (output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    import os
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT/'results/.mplconfig'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    penalty = float(penalties[0])
    group = [row for row in aggregates if row['yield_penalty_s'] == penalty]
    x = [row['shuttles'] for row in group]
    busy = [100*row['reader_busy_fraction_mean'] for row in group]
    deviation = [100*row['reader_busy_fraction_sd'] for row in group]
    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    ax.errorbar(x, busy, yerr=deviation, marker='o', capsize=4, color='#547465', linewidth=2.5, markersize=8)
    for shuttle_count, value in zip(x, busy):
        ax.annotate(f'{value:.1f}%', (shuttle_count, value), xytext=(0, 11), textcoords='offset points', ha='center', fontsize=10, color='#21352E')
    ax.set(xlabel='Shuttles per partition', ylabel='Reader busy time (%)', xticks=x, ylim=(0, 105), title='Reader utilization versus shuttle count')
    ax.spines[['top','right']].set_visible(False)
    fig.suptitle('Fixed setup: 1 reader, 8 rows, 16 m, read=8 s, B=8, Non-Zone FIFO, 3 s yield penalty')
    fig.tight_layout()
    fig.savefig(output/'fig_shuttle_count.png', dpi=190)
    plt.close(fig)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
