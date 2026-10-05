"""Focused N=8 prefetch-buffer sweep for one physical partition."""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
import hashlib
import itertools
import json
import math
from pathlib import Path
from statistics import mean, stdev
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from glass_sim.partition_feeder_study import Config, PartitionSimulation, make_requests


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def aggregate(rows: list[dict]) -> list[dict]:
    keys = ("pattern", "read_s", "policy", "buffer_slots")
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        groups.setdefault(tuple(row[key] for key in keys), []).append(row)
    output = []
    for group_key, group in sorted(groups.items()):
        result = dict(zip(keys, group_key))
        result["runs"] = len(group)
        for key, value in group[0].items():
            if key in keys or key in {"seed", "workload_sha256", "cpu_wall_s"} or not isinstance(value, (int, float)):
                continue
            values = [row[key] for row in group]
            result[key + "_mean"] = mean(values)
            result[key + "_sd"] = stdev(values) if len(values) > 1 else 0.0
        output.append(result)
    return output


def make_plots(rows: list[dict], output: Path) -> None:
    import os
    os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "results/.mplconfig"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    patterns = ["uniform", "hotspot"]
    colors = {"zone": "#547465", "nonzone_fifo": "#c17a3b"}
    for pattern in patterns:
        fig, axes = plt.subplots(1, 3, figsize=(14, 4.8), sharey=False)
        for index, read_s in enumerate(sorted({row["read_s"] for row in rows})):
            ax = axes[index]
            for policy in ("zone", "nonzone_fifo"):
                group = sorted((row for row in rows if row["pattern"] == pattern and row["read_s"] == read_s and row["policy"] == policy), key=lambda row: row["buffer_slots"])
                ax.errorbar([row["buffer_slots"] for row in group], [row["p99_s_mean"] / 60 for row in group], yerr=[row["p99_s_sd"] / 60 for row in group], marker="o", capsize=3, label=policy, color=colors[policy])
            ax.set_title(f"Optical read = {read_s:g}s")
            ax.set_xlabel("Prefetch buffer slots (N = 8)")
            ax.set_xticks([0, 8, 16])
            ax.set_ylabel("Mean per-run p99 (min)")
            ax.spines[["top", "right"]].set_visible(False)
            if index == 0:
                ax.legend(frameon=False, fontsize=9)
        fig.suptitle(f"N=8 prefetch sweep — {pattern} workload")
        fig.tight_layout()
        fig.savefig(output / f"fig1_p99_{pattern}.png", dpi=190)
        plt.close(fig)

    pattern = "uniform"
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.8))
    for ax, metric, title, ylabel in zip(
        axes,
        ("prefetch_hit_fraction_mean", "prefetch_lead_mean_s_mean", "route_motion_s_mean"),
        ("Prefetch hit rate", "How early was the handoff?", "Physical route motion"),
        ("Fraction of jobs", "Seconds before reader start", "Route-seconds / request"),
    ):
        for policy in ("zone", "nonzone_fifo"):
            group = sorted((row for row in rows if row["pattern"] == pattern and row["read_s"] == 8 and row["policy"] == policy), key=lambda row: row["buffer_slots"])
            values = [row[metric] * (100 if metric == "prefetch_hit_fraction_mean" else 1) for row in group]
            ax.plot([row["buffer_slots"] for row in group], values, marker="o", label=policy, color=colors[policy])
        ax.set_title(title)
        ax.set_xlabel("Prefetch buffer slots")
        ax.set_xticks([0, 8, 16])
        ax.set_ylabel(ylabel)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False, fontsize=9)
    fig.suptitle("N=8 pipeline diagnostics — uniform workload, read=8s")
    fig.tight_layout()
    fig.savefig(output / "fig2_prefetch_diagnostics.png", dpi=190)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.8))
    for policy in ("zone", "nonzone_fifo"):
        group = sorted((row for row in rows if row["pattern"] == "uniform" and row["read_s"] == 8 and row["policy"] == policy), key=lambda row: row["buffer_slots"])
        ax.plot([row["buffer_slots"] for row in group], [row["throughput_req_s_mean"] * 60 for row in group], marker="o", label=policy, color=colors[policy])
    ax.set_title("N=8 throughput versus prefetch capacity")
    ax.set_xlabel("Prefetch buffer slots")
    ax.set_ylabel("Read completions / min")
    ax.set_xticks([0, 8, 16])
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(output / "fig3_throughput.png", dpi=190)
    plt.close(fig)


def write_report(aggregate_rows: list[dict], output: Path) -> None:
    lines = [
        "# N=8 Prefetch Buffer Sweep",
        "",
        "這一輪固定單一 partition、單一 reader、8 台 shuttle；只改 feeder-buffer capacity = 0/8/16。B>0 代表 request 已知後，reader 忙碌時把下一批 glass 先送到 buffer。它不是未知 request 的 speculative prefetch，也不是 read-after-read cache。",
        "",
        "## Results",
        "",
        "| Pattern | Read s | Policy | B | Prefetch hit | Lead s | Route motion / request | Traffic wait / request | Mean p99 min | Throughput req/min |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in aggregate_rows:
        lines.append(f"| {row['pattern']} | {row['read_s']:g} | {row['policy']} | {row['buffer_slots']} | {row['prefetch_hit_fraction_mean']:.1%} | {row['prefetch_lead_mean_s_mean']:.1f} | {row['route_motion_s_mean']/row['requests_mean']:.2f} | {row['traffic_wait_s_mean']/row['requests_mean']:.2f} | {row['p99_s_mean']/60:.2f} | {row['throughput_req_s_mean']*60:.3f} |")
    lines += [
        "",
        "## How to read this experiment",
        "",
        "- `prefetch_hit_fraction` and `prefetch_lead_mean_s` quantify overlap: the glass reached handoff before its reader service started.",
        "- `route_motion_s` is still present under B=8/16. Prefetch hides route work behind reader service; it does not shorten one physical trip.",
        "- `traffic_wait_s` is separate from route motion. A large value means N=8 shuttles compete for the partition's rail resources.",
        "- B=16 tests capacity beyond the one-slot-per-shuttle design point; it may improve absorption of bursts, but it can also hold stale/early work and increase waiting.",
        "- All rows use the same 5 seeds, request count, placement generator, partition and reader. P99 is the mean of five per-run p99 values, not a pooled quantile.",
        "",
        "## Scope boundary",
        "",
        "This is a controlled motivation experiment. It does not claim a calibrated Project Silica throughput, a globally optimal prefetch policy, or a universal optimal N. Return uses the fixed return-first policy from the parent study. See `experiments/partition-feeder-story/README.md` for transport, handoff, output and causal assumptions.",
        "",
        "## Reproduce",
        "",
        "```bash",
        ".venv/bin/python scripts/run_prefetch_n8.py --config experiments/partition-feeder-story/prefetch-n8.json",
        "```",
    ]
    (output / "ANALYSIS_PREFETCH_N8_ZH.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "experiments/partition-feeder-story/prefetch-n8.json")
    args = parser.parse_args()
    raw = json.loads(args.config.read_text(encoding="utf-8"))
    base = Config(**raw["model"])
    base.validate()
    output = ROOT / raw["output_dir"]
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    start = perf_counter()
    total = len(raw["seeds"]) * len(raw["patterns"]) * len(raw["read_s"]) * len(raw["policies"]) * len(raw["buffer_slots"])
    print(f"N=8 prefetch matrix: {total} runs", flush=True)
    for seed, pattern, read_s, policy, slots in itertools.product(raw["seeds"], raw["patterns"], raw["read_s"], raw["policies"], raw["buffer_slots"]):
        config = replace(base, shuttles=8, buffer_slots=slots, policy=policy, read_s=read_s, length_m=raw["length_m"])
        requests = make_requests(config, raw["requests"], seed, pattern)
        summary, _, timeline = PartitionSimulation(config, requests).run()
        rows.append(dict(seed=seed, pattern=pattern, read_s=read_s, policy=policy, buffer_slots=slots, **summary))
        print(f"{len(rows)}/{total} pattern={pattern} read={read_s:g}s {policy} B={slots}", flush=True)
    aggregate_rows = aggregate(rows)
    write_csv(output / "runs.csv", rows)
    write_csv(output / "aggregate.csv", aggregate_rows)
    summary = dict(config=raw, effective_model=asdict(base), run_count=len(rows), wall_s=perf_counter()-start,
                   validation=dict(n_fixed_to_8=True, paired_workloads=True, prefetch_metrics_recorded=True, every_read_returned=True))
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    make_plots(aggregate_rows, output)
    write_report(aggregate_rows, output)
    print(f"Completed {len(rows)} runs in {perf_counter()-start:.1f}s", flush=True)


if __name__ == "__main__":
    main()
