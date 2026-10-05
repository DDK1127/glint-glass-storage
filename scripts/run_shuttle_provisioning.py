"""Shuttle-count sweep: one partition, one reader, all other parameters fixed.

Answers "how many shuttles should one reader get?" by comparing the measured
reader utilization against an ideal no-interference line scaled from N=1.
"""
from __future__ import annotations

import argparse
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

ZONE_GREEN = '#547465'
IDEAL_GRAY = '#8C9A93'
INK = '#21352E'
MUTED = '#5F7069'


def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def aggregate(runs, shuttle_counts, penalty):
    rows = []
    for shuttle_count in shuttle_counts:
        group = [r for r in runs if r['shuttles'] == shuttle_count and r['yield_penalty_s'] == penalty]
        item = {'shuttles': shuttle_count, 'yield_penalty_s': penalty, 'runs': len(group)}
        for key, value in group[0].items():
            if key in {'seed', 'shuttles', 'yield_penalty_s', 'workload_sha256'} or not isinstance(value, (int, float)):
                continue
            values = [r[key] for r in group]
            item[key+'_mean'] = mean(values)
            item[key+'_sd'] = stdev(values) if len(values) > 1 else 0.0
        rows.append(item)
    return rows


def ideal_analysis(rows, config):
    """Ideal line: N independent copies of the single-shuttle cycle, capped by the reader."""
    single = rows[0]
    assert single['shuttles'] == 1
    shuttle_cycle_s = 1 / single['throughput_req_s_mean']
    reader_cycle_s = config.cycle_s
    ideal_ratio = shuttle_cycle_s / reader_cycle_s
    for row in rows:
        row['ideal_reader_busy_fraction'] = min(1.0, row['shuttles'] * single['reader_busy_fraction_mean'])
        row['interference_gap_pct'] = 100 * (row['ideal_reader_busy_fraction'] - row['reader_busy_fraction_mean'])
        row['traffic_wait_per_request_s'] = row['traffic_wait_s_mean'] / row['requests_mean']
        row['throughput_req_min'] = 60 * row['throughput_req_s_mean']
        row['p99_min'] = row['p99_s_mean'] / 60
    for previous, row in zip(rows, rows[1:]):
        added = row['shuttles'] - previous['shuttles']
        row['marginal_busy_pct_per_added_shuttle'] = 100 * (row['reader_busy_fraction_mean'] - previous['reader_busy_fraction_mean']) / added
    rows[0]['marginal_busy_pct_per_added_shuttle'] = 100 * rows[0]['reader_busy_fraction_mean']
    first = lambda threshold: next((r['shuttles'] for r in rows if r['reader_busy_fraction_mean'] >= threshold), None)
    return {
        'single_shuttle_cycle_s': shuttle_cycle_s,
        'reader_cycle_s': reader_cycle_s,
        'ideal_shuttles_per_reader': ideal_ratio,
        'smallest_n_busy_ge_80pct': first(.80),
        'smallest_n_busy_ge_90pct': first(.90),
        'smallest_n_busy_ge_95pct': first(.95),
        'peak_throughput_shuttles': max(rows, key=lambda r: r['throughput_req_s_mean'])['shuttles'],
    }


def plot(rows, analysis, raw, output):
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT/'results/.mplconfig'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size': 11, 'axes.edgecolor': '#BBC8C0', 'axes.labelcolor': INK,
                         'xtick.color': MUTED, 'ytick.color': MUTED})
    x = [r['shuttles'] for r in rows]
    subtitle = (f"1 reader · 8 rows · {raw['length_m']:g} m · read={raw['read_s']:g} s · "
                f"B={raw['buffer_slots']} · Non-Zone FIFO · {len(raw['seeds'])} seeds × {raw['requests']} requests")

    # Figure 1: utilization, measured vs ideal.
    fig, ax = plt.subplots(figsize=(8.6, 4.8))
    ax.plot(x, [100*r['ideal_reader_busy_fraction'] for r in rows], linestyle='--', color=IDEAL_GRAY,
            linewidth=2, label='Ideal (no interference, scaled from N=1)')
    ax.errorbar(x, [100*r['reader_busy_fraction_mean'] for r in rows],
                yerr=[100*r['reader_busy_fraction_sd'] for r in rows], marker='o', markersize=7,
                capsize=3, color=ZONE_GREEN, linewidth=2, label='Simulated (mean ± SD)')
    for r in rows:
        if r['shuttles'] in (1, 4, 8, 16, 32) or r['shuttles'] == analysis['smallest_n_busy_ge_90pct']:
            ax.annotate(f"{100*r['reader_busy_fraction_mean']:.0f}%", (r['shuttles'], 100*r['reader_busy_fraction_mean']),
                        xytext=(0, -16), textcoords='offset points', ha='center', fontsize=9.5, color=INK)
    ax.axvline(analysis['ideal_shuttles_per_reader'], color=IDEAL_GRAY, linewidth=1, linestyle=':')
    ax.text(analysis['ideal_shuttles_per_reader'], 22, f" ideal ratio ≈ {analysis['ideal_shuttles_per_reader']:.1f}",
            color=MUTED, fontsize=9.5, va='center', ha='left')
    ax.axhline(90, color='#DFE7E2', linewidth=1, zorder=0)
    ax.set(xscale='log', xticks=x, xticklabels=[str(v) for v in x], ylim=(0, 108),
           xlabel='Shuttles per partition (1 reader)', ylabel='Reader busy time (%)')
    ax.minorticks_off()
    ax.spines[['top', 'right']].set_visible(False)
    ax.legend(frameon=False, loc='lower right')
    ax.text(x[0], 90.8, '90% target', color=MUTED, fontsize=9, ha='left', va='bottom')
    ax.set_title(subtitle, fontsize=9.5, color=MUTED)
    fig.tight_layout()
    fig.savefig(output/'fig_shuttle_count.png', dpi=190)
    plt.close(fig)

    # Figure 2: what the extra shuttles buy and cost (small multiples, one axis each).
    panels = [('throughput_req_min', 'Read completions / min'),
              ('p99_min', 'p99 latency (min)'),
              ('traffic_wait_per_request_s', 'Traffic wait (shuttle-s / request)')]
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 3.9))
    for ax, (key, label) in zip(axes, panels):
        ax.plot(x, [r[key] for r in rows], marker='o', markersize=6, color=ZONE_GREEN, linewidth=2)
        ax.set(xscale='log', xticks=x, xticklabels=[str(v) for v in x], title=label, xlabel='Shuttles')
        ax.minorticks_off()
        ax.set_ylim(bottom=0)
        ax.title.set_color(INK)
        ax.tick_params(axis='x', labelsize=8.5)
        ax.spines[['top', 'right']].set_visible(False)
    fig.suptitle(subtitle, fontsize=9.5, color=MUTED)
    fig.tight_layout()
    fig.savefig(output/'fig_shuttle_tradeoff.png', dpi=190)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'experiments/partition-feeder-story/shuttle-provisioning.json')
    args = parser.parse_args()
    raw = json.loads(args.config.read_text(encoding='utf-8'))
    base = Config(**raw['model'])
    output = ROOT/raw['output_dir']
    output.mkdir(parents=True, exist_ok=True)
    penalties = [float(p) for p in raw.get('yield_penalties_s', [0.0])]
    shuttle_counts = sorted(raw['shuttles'])
    if shuttle_counts[0] != 1:
        raise ValueError('The ideal line is scaled from N=1; include 1 shuttle')
    runs, started = [], perf_counter()
    for seed in raw['seeds']:
        for shuttle_count in shuttle_counts:
            for penalty in penalties:
                config = replace(base, shuttles=shuttle_count, length_m=float(raw['length_m']), read_s=float(raw['read_s']),
                                 buffer_slots=raw['buffer_slots'], policy=raw['policy'], yield_penalty_s=penalty)
                config.validate()
                requests = make_requests(config, raw['requests'], seed, raw['pattern'])
                metrics, _, _ = PartitionSimulation(config, requests).run()
                runs.append(dict(seed=seed, shuttles=shuttle_count, yield_penalty_s=penalty, **metrics))
    common = replace(base, length_m=float(raw['length_m']), read_s=float(raw['read_s']), buffer_slots=raw['buffer_slots'],
                     policy=raw['policy'], yield_penalty_s=penalties[0])
    aggregates, analyses = [], {}
    for penalty in penalties:
        rows = aggregate(runs, shuttle_counts, penalty)
        analyses[str(penalty)] = ideal_analysis(rows, common)
        aggregates.extend(rows)
    write_csv(output/'runs.csv', runs)
    write_csv(output/'aggregate.csv', aggregates)
    summary = {'config': raw, 'effective_common': asdict(common), 'run_count': len(runs),
               'analysis_by_penalty': analyses,
               'ideal_definition': 'N x (N=1 reader busy fraction), capped at 100%; ideal ratio = (1 / N=1 throughput) / (load+read+unload)',
               'wall_s': perf_counter()-started}
    (output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    plot([r for r in aggregates if r['yield_penalty_s'] == penalties[0]], analyses[str(penalties[0])], raw, output)
    print(json.dumps(analyses, indent=2))


if __name__ == '__main__':
    main()
