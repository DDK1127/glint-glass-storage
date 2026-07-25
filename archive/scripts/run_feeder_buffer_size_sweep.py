from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("MPLCONFIGDIR", str(Path("outputs/.mplconfig").resolve()))
os.environ.setdefault("XDG_CACHE_HOME", str(Path("outputs/.cache").resolve()))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from glass_v2.single_reader_scaling import (
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
RED = "#B84A4A"


def main() -> None:
    parser = argparse.ArgumentParser(description="Sweep feeder-buffer size versus shuttle count.")
    parser.add_argument("--base-config", default="configs/single-reader-large-batch-64g-synthetic-feeder-rack3s-to64.json")
    parser.add_argument("--output-dir", default="outputs/feeder-buffer-size-sweep-rack3s-batch500k")
    parser.add_argument("--batch-size", type=int, default=500000)
    parser.add_argument("--feeder-slots", default="1,2,4,8,16,32,64,128")
    parser.add_argument("--max-shuttles", type=int, default=16)
    args = parser.parse_args()

    feeder_slots = [int(value) for value in args.feeder_slots.split(",") if value.strip()]
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
    for slots in feeder_slots:
        config = replace(
            base_config,
            feeder_buffer=replace(base_config.feeder_buffer, enabled=True, slots=slots),
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
            service_ops = float(result.summary["service_operation_count"])
            rows.append(
                {
                    "feeder_slots": slots,
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
                    "shuttle_utilization_max": result.summary["shuttle_utilization_max"],
                    "reader_waiting_for_glass_s": result.summary["reader_waiting_for_glass_s"],
                    "reader_waiting_for_glass_s_per_op": result.summary["reader_waiting_for_glass_s"] / service_ops,
                    "feeder_buffer_wait_for_slot_s": result.summary["feeder_buffer_wait_for_slot_s"],
                    "feeder_buffer_wait_for_slot_s_per_op": result.summary["feeder_buffer_wait_for_slot_s"] / service_ops,
                    "feeder_buffer_max_occupancy": result.summary["feeder_buffer_max_occupancy"],
                    "marginal_throughput_gain": marginal_gain,
                    "saturation_flag": saturation_flag,
                    "saturation_seen": saturation_seen,
                }
            )
            previous_throughput = throughput

    feeder_summary = summarize_by_slots(rows)
    shuttle_summary = summarize_by_shuttle(rows)
    write_csv(output_dir / "summary.csv", rows)
    write_csv(output_dir / "feeder_size_summary.csv", feeder_summary)
    write_csv(output_dir / "shuttle_summary.csv", shuttle_summary)
    write_config_snapshot(output_dir / "config.json", args, feeder_slots, shuttle_counts, base_config)
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    plot_throughput_lines(rows, figures_dir)
    plot_heatmap(rows, figures_dir)
    plot_required_buffer(shuttle_summary, figures_dir)
    plot_wait_breakdown(rows, figures_dir)
    plot_combined(rows, feeder_summary, shuttle_summary, figures_dir)
    write_analysis(output_dir / "FEEDER_BUFFER_SIZE_ANALYSIS.md", feeder_summary, shuttle_summary)


def summarize_by_slots(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summary = []
    for slots in sorted({int(row["feeder_slots"]) for row in rows}):
        series = sorted([row for row in rows if int(row["feeder_slots"]) == slots], key=lambda row: int(row["shuttle_count"]))
        best = max(series, key=lambda row: float(row["throughput_req_per_s"]))
        peak = float(best["throughput_req_per_s"])
        shuttle_95 = next(row for row in series if float(row["throughput_req_per_s"]) >= 0.95 * peak)
        saturation = next((row for row in series if row["saturation_flag"] is True), None)
        row4 = next((row for row in series if int(row["shuttle_count"]) == 4), best)
        summary.append(
            {
                "feeder_slots": slots,
                "best_shuttle_count": best["shuttle_count"],
                "shuttles_for_95pct_peak": shuttle_95["shuttle_count"],
                "saturation_shuttle_count": saturation["shuttle_count"] if saturation else "",
                "best_throughput_req_per_s": best["throughput_req_per_s"],
                "best_glass_ops_per_s": best["glass_ops_per_s"],
                "completion_min": float(best["drive_makespan_s"]) / 60.0,
                "system_drain_min": float(best["system_drain_s"]) / 60.0,
                "reader_pipeline_utilization": best["reader_pipeline_utilization"],
                "reader_wait_s_per_op_at_4shuttle": row4["reader_waiting_for_glass_s_per_op"],
                "buffer_wait_s_per_op_at_4shuttle": row4["feeder_buffer_wait_for_slot_s_per_op"],
                "max_occupancy_at_4shuttle": row4["feeder_buffer_max_occupancy"],
                "service_operation_count": best["service_operation_count"],
                "requests_per_service": best["requests_per_service"],
            }
        )
    return summary


def summarize_by_shuttle(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summary = []
    for shuttle in sorted({int(row["shuttle_count"]) for row in rows}):
        series = sorted([row for row in rows if int(row["shuttle_count"]) == shuttle], key=lambda row: int(row["feeder_slots"]))
        best = max(series, key=lambda row: float(row["throughput_req_per_s"]))
        peak = float(best["throughput_req_per_s"])
        slots_95 = next(row for row in series if float(row["throughput_req_per_s"]) >= 0.95 * peak)
        first_peak = next(row for row in series if float(row["throughput_req_per_s"]) >= peak * (1.0 - 1e-12))
        min_wait = min(
            series,
            key=lambda row: (
                float(row["reader_waiting_for_glass_s_per_op"])
                + float(row["feeder_buffer_wait_for_slot_s_per_op"]),
                int(row["feeder_slots"]),
            ),
        )
        summary.append(
            {
                "shuttle_count": shuttle,
                "throughput_sufficient_slots_95pct": slots_95["feeder_slots"],
                "first_peak_throughput_slots": first_peak["feeder_slots"],
                "min_total_wait_slots": min_wait["feeder_slots"],
                "best_throughput_req_per_s": best["throughput_req_per_s"],
                "best_glass_ops_per_s": best["glass_ops_per_s"],
                "reader_pipeline_utilization": best["reader_pipeline_utilization"],
                "reader_wait_s_per_op_at_95pct": slots_95["reader_waiting_for_glass_s_per_op"],
                "buffer_wait_s_per_op_at_95pct": slots_95["feeder_buffer_wait_for_slot_s_per_op"],
                "min_total_wait_s_per_op": (
                    float(min_wait["reader_waiting_for_glass_s_per_op"])
                    + float(min_wait["feeder_buffer_wait_for_slot_s_per_op"])
                ),
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


def write_config_snapshot(path: Path, args: argparse.Namespace, feeder_slots: list[int], shuttle_counts: list[int], base_config) -> None:
    payload = {
        "base_config": args.base_config,
        "batch_size": args.batch_size,
        "feeder_slots": feeder_slots,
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


def color_map(values: list[int]):
    cmap = plt.get_cmap("viridis")
    return {value: cmap(index / max(1, len(values) - 1)) for index, value in enumerate(values)}


def plot_throughput_lines(rows: list[dict[str, object]], figures_dir: Path) -> None:
    slots_values = sorted({int(row["feeder_slots"]) for row in rows})
    colors = color_map(slots_values)
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    for slots in slots_values:
        series = sorted([row for row in rows if int(row["feeder_slots"]) == slots], key=lambda row: int(row["shuttle_count"]))
        ax.plot(
            [int(row["shuttle_count"]) for row in series],
            [float(row["throughput_req_per_s"]) for row in series],
            marker="o",
            markersize=3,
            linewidth=1.8,
            color=colors[slots],
            label=f"{slots}",
        )
    ax.set_xlabel("Number of shuttles")
    ax.set_ylabel("Throughput (req/s)")
    ax.set_title("Feeder-buffer size vs. shuttle scaling")
    ax.set_xticks([1, 2, 4, 8, 12, 16])
    ax.legend(title="Feeder slots", frameon=False, fontsize=8, title_fontsize=8, ncol=2)
    apply_style(ax)
    save(fig, figures_dir, "feeder_size_throughput_lines")


def plot_heatmap(rows: list[dict[str, object]], figures_dir: Path) -> None:
    slots_values = sorted({int(row["feeder_slots"]) for row in rows})
    shuttles = sorted({int(row["shuttle_count"]) for row in rows})
    lookup = {
        (int(row["feeder_slots"]), int(row["shuttle_count"])): float(row["throughput_req_per_s"])
        for row in rows
    }
    values = [[lookup[(slots, shuttle)] for shuttle in shuttles] for slots in slots_values]
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    image = ax.imshow(values, aspect="auto", origin="lower", cmap="viridis")
    ax.set_xticks(range(len(shuttles)), shuttles)
    ax.set_yticks(range(len(slots_values)), slots_values)
    ax.set_xlabel("Number of shuttles")
    ax.set_ylabel("Feeder buffer slots")
    ax.set_title("Throughput heatmap")
    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label("Throughput (req/s)")
    save(fig, figures_dir, "feeder_size_throughput_heatmap")


def plot_required_buffer(shuttle_summary: list[dict[str, object]], figures_dir: Path) -> None:
    shuttles = [int(row["shuttle_count"]) for row in shuttle_summary]
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    ax.plot(
        shuttles,
        [int(row["throughput_sufficient_slots_95pct"]) for row in shuttle_summary],
        marker="o",
        color=BLUE,
        label="Slots for >=95% peak throughput",
    )
    ax.plot(
        shuttles,
        [int(row["first_peak_throughput_slots"]) for row in shuttle_summary],
        marker="s",
        color=ORANGE,
        label="First slot count at peak throughput",
    )
    ax.set_xlabel("Number of shuttles")
    ax.set_ylabel("Feeder buffer slots")
    ax.set_title("Throughput-sufficient feeder slots by shuttle count")
    ax.set_xticks([1, 2, 4, 8, 12, 16])
    ax.set_yscale("log", base=2)
    ax.set_yticks([1, 2, 4, 8, 16, 32, 64, 128], [1, 2, 4, 8, 16, 32, 64, 128])
    ax.legend(frameon=False, fontsize=8)
    apply_style(ax)
    save(fig, figures_dir, "feeder_size_required_slots")


def plot_wait_breakdown(rows: list[dict[str, object]], figures_dir: Path) -> None:
    selected = sorted([row for row in rows if int(row["shuttle_count"]) == 4], key=lambda row: int(row["feeder_slots"]))
    slots = [int(row["feeder_slots"]) for row in selected]
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    ax.plot(slots, [float(row["reader_waiting_for_glass_s_per_op"]) for row in selected], marker="o", color=GREEN, label="Reader wait/glass")
    ax.plot(slots, [float(row["feeder_buffer_wait_for_slot_s_per_op"]) for row in selected], marker="s", color=GRAY, label="Buffer wait/glass")
    ax.set_xscale("log", base=2)
    ax.set_xticks(slots, slots)
    ax.set_xlabel("Feeder buffer slots")
    ax.set_ylabel("Wait time (s/glass)")
    ax.set_title("At 4 shuttles, larger buffers trade reader wait for buffer slack")
    ax.legend(frameon=False)
    apply_style(ax)
    save(fig, figures_dir, "feeder_size_wait_breakdown_4shuttles")


def plot_combined(rows: list[dict[str, object]], feeder_summary: list[dict[str, object]], shuttle_summary: list[dict[str, object]], figures_dir: Path) -> None:
    slots_values = sorted({int(row["feeder_slots"]) for row in rows})
    colors = color_map(slots_values)
    fig, axes = plt.subplots(2, 2, figsize=(9.2, 6.4))

    ax = axes[0][0]
    for slots in slots_values:
        series = sorted([row for row in rows if int(row["feeder_slots"]) == slots], key=lambda row: int(row["shuttle_count"]))
        ax.plot([int(row["shuttle_count"]) for row in series], [float(row["throughput_req_per_s"]) for row in series], marker="o", markersize=2.8, linewidth=1.5, color=colors[slots], label=f"{slots}")
    ax.set_xlabel("Shuttles")
    ax.set_ylabel("Req/s")
    ax.set_title("(a) Throughput scaling")
    ax.set_xticks([1, 2, 4, 8, 12, 16])
    apply_style(ax)

    ax = axes[0][1]
    selected = sorted([row for row in rows if int(row["shuttle_count"]) == 4], key=lambda row: int(row["feeder_slots"]))
    ax.plot([int(row["feeder_slots"]) for row in selected], [float(row["reader_waiting_for_glass_s_per_op"]) for row in selected], marker="o", color=GREEN, label="Reader wait")
    ax.plot([int(row["feeder_slots"]) for row in selected], [float(row["feeder_buffer_wait_for_slot_s_per_op"]) for row in selected], marker="s", color=GRAY, label="Buffer wait")
    ax.set_xscale("log", base=2)
    ax.set_xticks([1, 2, 4, 8, 16, 32, 64, 128], [1, 2, 4, 8, 16, 32, 64, 128])
    ax.set_xlabel("Feeder slots")
    ax.set_ylabel("s/glass")
    ax.set_title("(b) Wait at 4 shuttles")
    ax.legend(frameon=False, fontsize=8)
    apply_style(ax)

    ax = axes[1][0]
    ax.plot([int(row["feeder_slots"]) for row in feeder_summary], [int(row["shuttles_for_95pct_peak"]) for row in feeder_summary], marker="o", color=BLUE)
    ax.set_xscale("log", base=2)
    ax.set_xticks([1, 2, 4, 8, 16, 32, 64, 128], [1, 2, 4, 8, 16, 32, 64, 128])
    ax.set_xlabel("Feeder slots")
    ax.set_ylabel("Shuttles for 95% peak")
    ax.set_title("(c) Shuttle need by buffer size")
    apply_style(ax)

    ax = axes[1][1]
    ax.plot([int(row["shuttle_count"]) for row in shuttle_summary], [int(row["throughput_sufficient_slots_95pct"]) for row in shuttle_summary], marker="o", color=PURPLE)
    ax.set_xlabel("Shuttles")
    ax.set_ylabel("Slots for >=95% peak")
    ax.set_yscale("log", base=2)
    ax.set_yticks([1, 2, 4, 8, 16, 32, 64, 128], [1, 2, 4, 8, 16, 32, 64, 128])
    ax.set_xticks([1, 2, 4, 8, 12, 16])
    ax.set_title("(d) Buffer slots needed")
    apply_style(ax)

    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, title="Feeder slots", loc="upper center", ncol=8, frameon=False, fontsize=8, title_fontsize=8)
    fig.subplots_adjust(top=0.88)
    save(fig, figures_dir, "feeder_size_combined_panel")


def write_analysis(path: Path, feeder_summary: list[dict[str, object]], shuttle_summary: list[dict[str, object]]) -> None:
    lines = [
        "# Feeder Buffer Size Analysis",
        "",
        "Experiment: single reader, feeder buffer enabled, rack pick/place 3s, reader load/unload 3s, rack length 4m, batch 500k, request merge enabled.",
        "",
        "## By Feeder Buffer Size",
        "",
        "| Feeder slots | Shuttles for 95% peak | Best shuttles | Best req/s | Reader util | Reader wait/glass @4S | Buffer wait/glass @4S | Max occupancy @4S |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in feeder_summary:
        lines.append(
            "| "
            f"{int(row['feeder_slots'])} | "
            f"{int(row['shuttles_for_95pct_peak'])} | "
            f"{int(row['best_shuttle_count'])} | "
            f"{float(row['best_throughput_req_per_s']):.4f} | "
            f"{float(row['reader_pipeline_utilization']):.1%} | "
            f"{float(row['reader_wait_s_per_op_at_4shuttle']):.2f} | "
            f"{float(row['buffer_wait_s_per_op_at_4shuttle']):.2f} | "
            f"{int(row['max_occupancy_at_4shuttle'])} |"
        )
    lines.extend(
        [
            "",
            "## By Shuttle Count",
            "",
            "| Shuttles | Slots for >=95% peak | First peak-throughput slots | Min-wait slots | Best req/s | Reader util |",
            "|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in shuttle_summary:
        if int(row["shuttle_count"]) not in {1, 2, 3, 4, 5, 8, 12, 16}:
            continue
        lines.append(
            "| "
            f"{int(row['shuttle_count'])} | "
            f"{int(row['throughput_sufficient_slots_95pct'])} | "
            f"{int(row['first_peak_throughput_slots'])} | "
            f"{int(row['min_total_wait_slots'])} | "
            f"{float(row['best_throughput_req_per_s']):.4f} | "
            f"{float(row['reader_pipeline_utilization']):.1%} |"
        )
    lines.extend(
        [
            "",
            "## Takeaways",
            "",
            "The `slots for >=95% peak` metric is a throughput-sufficiency metric, not a physical recommendation for how much staging space should be built.",
            "",
            "Once enough shuttles exist to saturate the single reader, even a small feeder can reach the same peak throughput. Extra shuttles then wait for feeder slots instead of increasing throughput.",
            "",
            "This is why the throughput-sufficient slot count can decrease at high shuttle counts: more shuttles compensate for a smaller buffer, but at the cost of more shuttle-side waiting.",
            "",
            "For an operational design choice, use the wait and occupancy metrics together with throughput. Larger buffers mainly reduce slot-blocking pressure and provide scheduling slack; they do not raise the reader-limited peak throughput.",
            "",
            "## Figures",
            "",
            "- `figures/feeder_size_throughput_lines.pdf`",
            "- `figures/feeder_size_throughput_heatmap.pdf`",
            "- `figures/feeder_size_required_slots.pdf`",
            "- `figures/feeder_size_wait_breakdown_4shuttles.pdf`",
            "- `figures/feeder_size_combined_panel.pdf`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
