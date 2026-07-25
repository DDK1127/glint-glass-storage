from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import json
import math
import os
from pathlib import Path
from statistics import mean
import sys

os.environ.setdefault("MPLCONFIGDIR", str(Path("outputs/.mplconfig").resolve()))
os.environ.setdefault("XDG_CACHE_HOME", str(Path("outputs/.cache").resolve()))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from glass_v2.single_reader_scaling import (
    GeometryConfig,
    SingleReaderScalingSimulator,
    _as_batch_at_t0,
    _load_read_requests,
    _merge_requests_by_platter,
    load_scaling_config,
)


TEXT = "#1F2933"
GRID = "#D7DEE8"
BLUE = "#2F6B9A"
ORANGE = "#D9822B"
GREEN = "#4C9F70"
PURPLE = "#6B5B95"
GRAY = "#7B8794"


def main() -> None:
    parser = argparse.ArgumentParser(description="Sweep rack length versus shuttle count.")
    parser.add_argument("--base-config", default="configs/single-reader-large-batch-64g-synthetic-feeder-rack3s-to64.json")
    parser.add_argument("--output-dir", default="outputs/rack-length-sweep-feeder-rack3s-batch500k")
    parser.add_argument("--batch-size", type=int, default=500000)
    parser.add_argument("--rack-lengths", default="2,4,6,8,12,16,24,32")
    parser.add_argument("--max-shuttles", type=int, default=16)
    args = parser.parse_args()

    rack_lengths = [float(value) for value in args.rack_lengths.split(",") if value.strip()]
    shuttle_counts = list(range(1, args.max_shuttles + 1))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    base_config = load_scaling_config(args.base_config)
    base_config = replace(
        base_config,
        output_dir=output_dir,
        max_requests=args.batch_size,
        batch_sizes=[args.batch_size],
        shuttle_counts=shuttle_counts,
    )

    requests, input_stats = _load_read_requests(base_config.trace_path, args.batch_size)
    batch_requests = _as_batch_at_t0(requests[: args.batch_size])
    if base_config.request_merge:
        batch_requests = _merge_requests_by_platter(batch_requests, base_config.geometry)

    rows = []
    for rack_length_m in rack_lengths:
        config = replace(
            base_config,
            geometry=replace_geometry(base_config.geometry, rack_length_m),
        )
        previous_throughput = None
        saturation_seen = False
        for shuttle_count in shuttle_counts:
            simulator = SingleReaderScalingSimulator(config, shuttle_count, input_stats)
            result = simulator.run(batch_requests)
            throughput = float(result.summary["throughput_req_per_s"])
            marginal_gain = None
            saturation_flag = False
            if previous_throughput is not None and previous_throughput > 0:
                marginal_gain = (throughput - previous_throughput) / previous_throughput
                saturation_flag = marginal_gain < config.saturation_threshold
            if saturation_flag:
                saturation_seen = True
            avg_fetch_s = mean(detail.fetch_s for detail in result.details) if result.details else 0.0
            avg_reader_pipeline_s = (
                (
                    result.summary["reader_load_time_s"]
                    + result.summary["reader_unload_time_s"]
                    + simulator.reader_busy_s
                )
                / len(result.details)
                if result.details
                else 0.0
            )
            rows.append(
                {
                    "rack_length_m": rack_length_m,
                    "storage_multiplier_vs_4m": rack_length_m / 4.0,
                    "shuttle_count": shuttle_count,
                    "batch_size": args.batch_size,
                    "request_count": result.summary["request_count"],
                    "service_operation_count": result.summary["service_operation_count"],
                    "requests_per_service": result.summary["request_count"] / result.summary["service_operation_count"],
                    "drive_makespan_s": result.summary["drive_makespan_s"],
                    "system_drain_s": result.summary["system_drain_s"],
                    "throughput_req_per_s": throughput,
                    "glass_ops_per_s": result.summary["service_operation_count"] / result.summary["drive_makespan_s"],
                    "reader_pipeline_utilization": result.summary["reader_pipeline_utilization"],
                    "shuttle_utilization_avg": result.summary["shuttle_utilization_avg"],
                    "reader_waiting_for_glass_s": result.summary["reader_waiting_for_glass_s"],
                    "feeder_buffer_wait_for_slot_s": result.summary["feeder_buffer_wait_for_slot_s"],
                    "avg_fetch_s_per_glass": avg_fetch_s,
                    "avg_reader_pipeline_s_per_glass": avg_reader_pipeline_s,
                    "marginal_throughput_gain": marginal_gain,
                    "saturation_flag": saturation_flag,
                    "saturation_seen": saturation_seen,
                }
            )
            previous_throughput = throughput

    summary_rows = summarize_by_rack_length(rows)
    write_csv(output_dir / "summary.csv", rows)
    write_csv(output_dir / "rack_length_summary.csv", summary_rows)
    write_config_snapshot(output_dir / "config.json", args, rack_lengths, shuttle_counts, base_config)
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    plot_throughput_lines(rows, figures_dir)
    plot_throughput_heatmap(rows, figures_dir)
    plot_required_shuttles(summary_rows, figures_dir)
    plot_time_model(summary_rows, figures_dir)
    plot_combined(rows, summary_rows, figures_dir)
    write_analysis(output_dir / "RACK_LENGTH_ANALYSIS.md", summary_rows)


def replace_geometry(geometry: GeometryConfig, rack_length_m: float) -> GeometryConfig:
    return replace(geometry, rack_length_m=rack_length_m)


def summarize_by_rack_length(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summary = []
    for rack_length in sorted({float(row["rack_length_m"]) for row in rows}):
        series = sorted([row for row in rows if float(row["rack_length_m"]) == rack_length], key=lambda row: int(row["shuttle_count"]))
        best = max(series, key=lambda row: float(row["throughput_req_per_s"]))
        peak = float(best["throughput_req_per_s"])
        shuttle_95 = next(row for row in series if float(row["throughput_req_per_s"]) >= 0.95 * peak)
        saturation = next((row for row in series if row["saturation_flag"] is True), None)
        one = series[0]
        estimated_required = math.ceil(float(one["avg_fetch_s_per_glass"]) / float(one["avg_reader_pipeline_s_per_glass"]))
        summary.append(
            {
                "rack_length_m": rack_length,
                "storage_multiplier_vs_4m": rack_length / 4.0,
                "best_shuttle_count": best["shuttle_count"],
                "shuttles_for_95pct_peak": shuttle_95["shuttle_count"],
                "saturation_shuttle_count": saturation["shuttle_count"] if saturation else "",
                "estimated_required_shuttles": estimated_required,
                "best_throughput_req_per_s": best["throughput_req_per_s"],
                "best_glass_ops_per_s": best["glass_ops_per_s"],
                "completion_min": float(best["drive_makespan_s"]) / 60.0,
                "reader_pipeline_utilization": best["reader_pipeline_utilization"],
                "avg_fetch_s_per_glass_1shuttle": one["avg_fetch_s_per_glass"],
                "avg_reader_pipeline_s_per_glass": one["avg_reader_pipeline_s_per_glass"],
                "service_operation_count": best["service_operation_count"],
                "requests_per_service": best["requests_per_service"],
            }
        )
    return summary


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_config_snapshot(path: Path, args: argparse.Namespace, rack_lengths: list[float], shuttle_counts: list[int], base_config) -> None:
    payload = {
        "base_config": args.base_config,
        "batch_size": args.batch_size,
        "rack_lengths_m": rack_lengths,
        "shuttle_counts": shuttle_counts,
        "base": base_config.to_json_dict(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def apply_style(ax) -> None:
    ax.set_facecolor("white")
    ax.grid(True, axis="y", color=GRID, linewidth=0.8)
    ax.grid(False, axis="x")
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color("#9AA5B1")
    ax.spines["bottom"].set_color("#9AA5B1")
    ax.tick_params(colors=TEXT, labelsize=9)
    ax.xaxis.label.set_color(TEXT)
    ax.yaxis.label.set_color(TEXT)
    ax.title.set_color(TEXT)


def save(fig, figures_dir: Path, name: str) -> None:
    fig.tight_layout()
    fig.savefig(figures_dir / f"{name}.pdf")
    fig.savefig(figures_dir / f"{name}.png", dpi=300)
    plt.close(fig)


def color_map(values: list[float]):
    cmap = plt.get_cmap("viridis")
    return {value: cmap(index / max(1, len(values) - 1)) for index, value in enumerate(values)}


def plot_throughput_lines(rows: list[dict[str, object]], figures_dir: Path) -> None:
    rack_lengths = sorted({float(row["rack_length_m"]) for row in rows})
    colors = color_map(rack_lengths)
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    for rack_length in rack_lengths:
        series = sorted([row for row in rows if float(row["rack_length_m"]) == rack_length], key=lambda row: int(row["shuttle_count"]))
        ax.plot(
            [int(row["shuttle_count"]) for row in series],
            [float(row["throughput_req_per_s"]) for row in series],
            marker="o",
            markersize=3,
            linewidth=1.8,
            color=colors[rack_length],
            label=f"{rack_length:g}m",
        )
    ax.set_xlabel("Number of shuttles")
    ax.set_ylabel("Throughput (req/s)")
    ax.set_title("Throughput vs. shuttle count under different rack lengths")
    ax.set_xticks([1, 2, 4, 8, 12, 16])
    ax.legend(title="Rack length", frameon=False, fontsize=8, title_fontsize=8, ncol=2)
    apply_style(ax)
    save(fig, figures_dir, "rack_length_throughput_lines")


def plot_throughput_heatmap(rows: list[dict[str, object]], figures_dir: Path) -> None:
    rack_lengths = sorted({float(row["rack_length_m"]) for row in rows})
    shuttles = sorted({int(row["shuttle_count"]) for row in rows})
    lookup = {
        (float(row["rack_length_m"]), int(row["shuttle_count"])): float(row["throughput_req_per_s"])
        for row in rows
    }
    values = [[lookup[(rack_length, shuttle)] for shuttle in shuttles] for rack_length in rack_lengths]
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    image = ax.imshow(values, aspect="auto", origin="lower", cmap="viridis")
    ax.set_xticks(range(len(shuttles)), shuttles)
    ax.set_yticks(range(len(rack_lengths)), [f"{value:g}" for value in rack_lengths])
    ax.set_xlabel("Number of shuttles")
    ax.set_ylabel("Rack length (m)")
    ax.set_title("Throughput heatmap")
    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label("Throughput (req/s)")
    save(fig, figures_dir, "rack_length_throughput_heatmap")


def plot_required_shuttles(summary_rows: list[dict[str, object]], figures_dir: Path) -> None:
    rack_lengths = [float(row["rack_length_m"]) for row in summary_rows]
    fig, ax1 = plt.subplots(figsize=(7.2, 4.0))
    ax1.plot(rack_lengths, [float(row["shuttles_for_95pct_peak"]) for row in summary_rows], marker="o", color=BLUE, label="Observed shuttles for 95% peak")
    ax1.plot(rack_lengths, [float(row["estimated_required_shuttles"]) for row in summary_rows], marker="s", color=ORANGE, label="Time-model estimate")
    ax1.set_xlabel("Rack length (m)")
    ax1.set_ylabel("Required shuttle count")
    ax1.set_title("Longer racks require more shuttles to keep the reader saturated")
    ax1.set_yticks([1, 2, 3, 4, 5, 6, 7, 8])
    ax2 = ax1.twinx()
    ax2.plot(rack_lengths, [float(row["storage_multiplier_vs_4m"]) for row in summary_rows], marker="^", color=GREEN, label="Storage multiplier")
    ax2.set_ylabel("Storage capacity vs. 4m")
    apply_style(ax1)
    ax2.spines["top"].set_visible(False)
    ax2.spines["left"].set_visible(False)
    ax2.spines["right"].set_color("#9AA5B1")
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2, frameon=False, fontsize=8, loc="upper left")
    save(fig, figures_dir, "rack_length_required_shuttles")


def plot_time_model(summary_rows: list[dict[str, object]], figures_dir: Path) -> None:
    rack_lengths = [float(row["rack_length_m"]) for row in summary_rows]
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    ax.plot(rack_lengths, [float(row["avg_fetch_s_per_glass_1shuttle"]) for row in summary_rows], marker="o", color=BLUE, label="1-shuttle fetch time")
    ax.plot(rack_lengths, [float(row["avg_reader_pipeline_s_per_glass"]) for row in summary_rows], linestyle="--", color=ORANGE, label="Reader service time")
    ax.set_xlabel("Rack length (m)")
    ax.set_ylabel("Seconds per glass")
    ax.set_title("Rack length increases shuttle fetch time, reader service stays fixed")
    ax.legend(frameon=False)
    apply_style(ax)
    save(fig, figures_dir, "rack_length_time_model")


def plot_combined(rows: list[dict[str, object]], summary_rows: list[dict[str, object]], figures_dir: Path) -> None:
    rack_lengths = sorted({float(row["rack_length_m"]) for row in rows})
    colors = color_map(rack_lengths)
    fig, axes = plt.subplots(2, 2, figsize=(9.2, 6.4))

    ax = axes[0][0]
    for rack_length in rack_lengths:
        series = sorted([row for row in rows if float(row["rack_length_m"]) == rack_length], key=lambda row: int(row["shuttle_count"]))
        ax.plot([int(row["shuttle_count"]) for row in series], [float(row["throughput_req_per_s"]) for row in series], marker="o", markersize=2.8, linewidth=1.5, color=colors[rack_length], label=f"{rack_length:g}m")
    ax.set_xlabel("Shuttles")
    ax.set_ylabel("Req/s")
    ax.set_title("(a) Throughput scaling")
    ax.set_xticks([1, 2, 4, 8, 12, 16])
    apply_style(ax)

    ax = axes[0][1]
    for rack_length in rack_lengths:
        series = sorted([row for row in rows if float(row["rack_length_m"]) == rack_length], key=lambda row: int(row["shuttle_count"]))
        ax.plot([int(row["shuttle_count"]) for row in series], [float(row["glass_ops_per_s"]) for row in series], marker="o", markersize=2.8, linewidth=1.5, color=colors[rack_length])
    ax.set_xlabel("Shuttles")
    ax.set_ylabel("Glass ops/s")
    ax.set_title("(b) Physical service rate")
    ax.set_xticks([1, 2, 4, 8, 12, 16])
    apply_style(ax)

    ax = axes[1][0]
    x = [float(row["rack_length_m"]) for row in summary_rows]
    ax.plot(x, [float(row["shuttles_for_95pct_peak"]) for row in summary_rows], marker="o", color=BLUE, label="Observed")
    ax.plot(x, [float(row["estimated_required_shuttles"]) for row in summary_rows], marker="s", color=ORANGE, label="Estimate")
    ax.set_xlabel("Rack length (m)")
    ax.set_ylabel("Required shuttles")
    ax.set_title("(c) Shuttles needed for saturation")
    ax.legend(frameon=False, fontsize=8)
    apply_style(ax)

    ax = axes[1][1]
    ax.plot(x, [float(row["avg_fetch_s_per_glass_1shuttle"]) for row in summary_rows], marker="o", color=BLUE, label="Fetch")
    ax.plot(x, [float(row["avg_reader_pipeline_s_per_glass"]) for row in summary_rows], linestyle="--", color=ORANGE, label="Reader")
    ax.set_xlabel("Rack length (m)")
    ax.set_ylabel("Seconds/glass")
    ax.set_title("(d) Fetch vs. reader service time")
    ax.legend(frameon=False, fontsize=8)
    apply_style(ax)

    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, title="Rack length", loc="upper center", ncol=8, frameon=False, fontsize=8, title_fontsize=8)
    fig.subplots_adjust(top=0.88)
    save(fig, figures_dir, "rack_length_combined_panel")


def write_analysis(path: Path, summary_rows: list[dict[str, object]]) -> None:
    lines = [
        "# Rack Length vs. Shuttle Scaling Analysis",
        "",
        "Experiment: feeder buffer enabled, rack pick/place 3s, reader load/unload 3s, batch 500k, request merge enabled.",
        "",
        "Interpretation note: in this model, longer rack length increases physical travel distance. Storage capacity is reported as a linear multiplier versus the 4m baseline.",
        "",
        "## Summary",
        "",
        "| Rack length | Storage vs 4m | 95% peak shuttles | Estimated shuttles | Best req/s | Glass ops/s | 1-shuttle fetch s/glass | Reader s/glass |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary_rows:
        lines.append(
            "| "
            f"{float(row['rack_length_m']):g}m | "
            f"{float(row['storage_multiplier_vs_4m']):.1f}x | "
            f"{int(row['shuttles_for_95pct_peak'])} | "
            f"{int(row['estimated_required_shuttles'])} | "
            f"{float(row['best_throughput_req_per_s']):.4f} | "
            f"{float(row['best_glass_ops_per_s']):.4f} | "
            f"{float(row['avg_fetch_s_per_glass_1shuttle']):.2f} | "
            f"{float(row['avg_reader_pipeline_s_per_glass']):.2f} |"
        )
    lines.extend(
        [
            "",
            "## Takeaways",
            "",
            "Longer racks increase storage capacity almost linearly, but they also increase shuttle fetch time.",
            "",
            "Throughput remains close to the single-reader limit as long as enough shuttles are added to keep the feeder buffer supplied.",
            "",
            "The required shuttle count grows stepwise rather than linearly. In this sweep, 4m to 12m remains around 4 shuttles, 16m to 24m needs around 5, and 32m needs around 6 to reach near-peak throughput.",
            "",
            "Once the reader is saturated, additional shuttles do not increase throughput; they mainly reduce reader wait until saturation and then create feeder-buffer waiting.",
            "",
            "## Figures",
            "",
            "- `figures/rack_length_throughput_lines.pdf`",
            "- `figures/rack_length_throughput_heatmap.pdf`",
            "- `figures/rack_length_required_shuttles.pdf`",
            "- `figures/rack_length_time_model.pdf`",
            "- `figures/rack_length_combined_panel.pdf`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
