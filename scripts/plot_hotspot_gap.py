"""Figures for results/hotspot-gap (reads gap.csv; run after run_hotspot_gap.py)."""
from __future__ import annotations

import csv
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'results/hotspot-gap'
INK, MUTED, GRID = '#21352E', '#5F7069', '#DFE7E2'
ZONE, WS, REF = '#547465', '#75639B', '#8C9A93'


def main(n_focus=8, hold=0.5):
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT/'results/.mplconfig'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size': 11, 'axes.edgecolor': '#BBC8C0', 'axes.labelcolor': INK,
                         'xtick.color': MUTED, 'ytick.color': MUTED})
    rows = list(csv.DictReader((OUT/'gap.csv').open(encoding='utf-8')))
    for r in rows:
        for k, v in r.items():
            try:
                r[k] = float(v)
            except ValueError:
                pass
    pick = lambda n, h, share, dwell: next(r for r in rows if r['shuttles'] == n and r['hold'] == h
                                           and r['hot_share'] == share and r['dwell'] == dwell)

    # Fig 1: imbalance cost and what work stealing recovers (focus N, primary congestion cost).
    shares, dwells = [0.30, 0.47, 0.60], [100.0, 500.0, 'static']
    titles = {100.0: 'Hotspot moves every 100 requests', 500.0: 'Moves every 500 requests', 'static': 'Hotspot stays put'}
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.3), sharey=True)
    for ax, dwell in zip(axes, dwells):
        cells = [pick(n_focus, hold, s, dwell) for s in shares]
        x = [100 * s for s in shares]
        ax.plot(x, [c['zone_p99'] for c in cells], marker='o', lw=2.2, ms=7, color=ZONE, label='Zone')
        ax.plot(x, [c['ws_best_p99'] for c in cells], marker='o', lw=2.2, ms=7, color=WS, label='Zone + work stealing (best-tuned)')
        ax.axhline(cells[0]['balanced_p99'], color=REF, ls='--', lw=1.8, label='Same system, balanced load')
        ax.axvspan(44, 50, color=GRID, zorder=0)
        ax.set(yscale='log', xticks=x, xlabel='Share of requests on the hot row (%)', title=titles[dwell])
        ax.title.set_color(INK)
        ax.spines[['top', 'right']].set_visible(False)
    axes[0].set_ylabel('p99 latency (min, log scale)')
    axes[0].legend(frameon=False, fontsize=9.5, loc='upper left')
    fig.suptitle(f'1 reader · {n_focus} shuttles · Zone = 1 row per shuttle · load 75% of balanced capacity · '
                 'shaded = Azure trace burst level (47%)', fontsize=9.5, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT/'fig_gap_zone_vs_ws.png', dpi=180)
    plt.close(fig)

    # Fig 2: share of the imbalance gap recovered by work stealing, by shuttle count.
    fig, ax = plt.subplots(figsize=(7.6, 4.3))
    ns, width = [2.0, 4.0, 8.0], 0.26
    for i, (dwell, shade) in enumerate(zip(dwells, ['#C9BFE0', '#9C8CC4', WS])):
        vals = [min(100, pick(n, hold, 0.47, dwell)['ws_recovered_pct']) for n in ns]
        bars = ax.bar([j + (i - 1) * width for j in range(3)], vals, width - .03, color=shade,
                      label=titles[dwell].replace('Hotspot ', '').capitalize())
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 2, f'{v:.0f}%', ha='center', fontsize=9, color=INK)
    ax.set(xticks=range(3), xticklabels=[f'{int(n)} shuttles' for n in ns], ylim=(0, 112),
           ylabel='Gap recovered by work stealing (%)')
    ax.axhline(100, color=GRID, lw=1)
    ax.spines[['top', 'right']].set_visible(False)
    ax.legend(frameon=False, fontsize=9.5, loc='upper right')
    ax.set_title('Hot row = 47% of requests · 1 reader · 100% = back to balanced', fontsize=9.5, color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT/'fig_gap_recovery_by_n.png', dpi=180)
    plt.close(fig)


if __name__ == '__main__':
    main()
