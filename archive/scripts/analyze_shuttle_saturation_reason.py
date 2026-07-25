from __future__ import annotations

import argparse
import csv
import math
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path("outputs/.mplconfig").resolve()))
os.environ.setdefault("XDG_CACHE_HOME", str(Path("outputs/.cache").resolve()))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


TEXT = "#1F2933"
GRID = "#D7DEE8"
BLUE = "#2F6B9A"
ORANGE = "#D9822B"
GREEN = "#4C9F70"
GRAY = "#7B8794"


def main() -> None:
    parser = argparse.ArgumentParser(description="Explain why shuttle scaling saturates.")
    parser.add_argument("--output-dir", default="outputs/single-reader-large-batch-64g-synthetic-feeder-rack3s-to64")
    parser.add_argument("--batch-size", type=int, default=500000)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    summary_rows = load_summary(output_dir / "summary.csv", args.batch_size)
    detail_stats = {
        shuttle: load_detail_stats(output_dir, args.batch_size, shuttle)
        for shuttle in [1, 2, 4, 8, 16, 32, 64]
    }

    base_fetch_s = detail_stats[1]["avg_fetch_s"]
    reader_pipeline_s = detail_stats[1]["avg_reader_pipeline_s"]
    required_shuttles = math.ceil(base_fetch_s / reader_pipeline_s)

    figures_dir = output_dir / "paper_figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    plot_supply_vs_reader(summary_rows, detail_stats, base_fetch_s, reader_pipeline_s, figures_dir)
    write_markdown(
        output_dir / "SATURATION_ANALYSIS.md",
        args.batch_size,
        summary_rows,
        detail_stats,
        base_fetch_s,
        reader_pipeline_s,
        required_shuttles,
    )


def load_summary(path: Path, batch_size: int) -> dict[int, dict[str, float]]:
    rows = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if int(row["batch_size"]) != batch_size:
                continue
            shuttle = int(row["shuttle_count"])
            rows[shuttle] = {
                "throughput_req_per_s": float(row["throughput_req_per_s"]),
                "drive_makespan_s": float(row["drive_makespan_s"]),
                "system_drain_s": float(row["system_drain_s"]),
                "service_operation_count": float(row["service_operation_count"]),
                "reader_pipeline_utilization": float(row["reader_pipeline_utilization"]),
                "reader_waiting_for_glass_s": float(row["reader_waiting_for_glass_s"]),
                "feeder_buffer_wait_for_slot_s": float(row["feeder_buffer_wait_for_slot_s"]),
                "shuttle_utilization_avg": float(row["shuttle_utilization_avg"]),
            }
    return rows


def load_detail_stats(output_dir: Path, batch_size: int, shuttle_count: int) -> dict[str, float]:
    path = output_dir / f"batch_{batch_size:05d}" / f"shuttles_{shuttle_count:02d}" / "request_detail.csv"
    service_ops = 0
    fetch_s = 0.0
    read_s = 0.0
    reader_wait_s = 0.0
    buffer_wait_s = 0.0
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            service_ops += 1
            fetch_s += float(row["fetch_s"])
            read_s += float(row["read_s"])
            reader_wait_s += float(row["reader_waiting_for_glass_s"])
            buffer_wait_s += float(row["feeder_buffer_wait_for_slot_s"])
    reader_load_s = service_ops * 3.0
    reader_unload_s = service_ops * 3.0
    reader_pipeline_s = reader_load_s + read_s + reader_unload_s
    return {
        "service_ops": float(service_ops),
        "avg_fetch_s": fetch_s / service_ops,
        "avg_read_s": read_s / service_ops,
        "avg_reader_pipeline_s": reader_pipeline_s / service_ops,
        "avg_reader_wait_s": reader_wait_s / service_ops,
        "avg_buffer_wait_s": buffer_wait_s / service_ops,
    }


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


def plot_supply_vs_reader(
    summary_rows: dict[int, dict[str, float]],
    detail_stats: dict[int, dict[str, float]],
    base_fetch_s: float,
    reader_pipeline_s: float,
    figures_dir: Path,
) -> None:
    shuttles = [1, 2, 4, 8, 16, 32, 64]
    estimated_supply_interval = [base_fetch_s / shuttle for shuttle in shuttles]
    actual_reader_wait = [detail_stats[shuttle]["avg_reader_wait_s"] for shuttle in shuttles]
    actual_buffer_wait = [detail_stats[shuttle]["avg_buffer_wait_s"] for shuttle in shuttles]

    fig, ax1 = plt.subplots(figsize=(7.4, 4.35))
    ax1.plot(
        shuttles,
        estimated_supply_interval,
        marker="o",
        linewidth=2.0,
        color=BLUE,
        label="Shuttle supply interval",
    )
    ax1.axhline(
        reader_pipeline_s,
        color=ORANGE,
        linestyle="--",
        linewidth=1.8,
        label="Reader service interval",
    )
    ax1.set_xscale("log", base=2)
    ax1.set_xticks(shuttles, shuttles)
    ax1.set_xlabel("Number of shuttles")
    ax1.set_ylabel("Supply/service interval (s per glass)")
    ax1.set_title("Shuttle scaling saturates once supply is faster than reader service")

    ax2 = ax1.twinx()
    ax2.plot(shuttles, actual_reader_wait, marker="s", linewidth=1.6, color=GREEN, label="Reader wait")
    ax2.plot(shuttles, actual_buffer_wait, marker="^", linewidth=1.6, color=GRAY, label="Feeder-buffer wait")
    ax2.set_ylabel("Observed wait (s per glass)")

    apply_style(ax1)
    ax2.spines["top"].set_visible(False)
    ax2.spines["left"].set_visible(False)
    ax2.spines["right"].set_color("#9AA5B1")
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    fig.legend(
        handles1 + handles2,
        labels1 + labels2,
        frameon=False,
        fontsize=8,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.995),
        ncol=4,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(figures_dir / "fig6_shuttle_saturation_time_model.pdf")
    fig.savefig(figures_dir / "fig6_shuttle_saturation_time_model.png", dpi=300)
    plt.close(fig)


def write_markdown(
    path: Path,
    batch_size: int,
    summary_rows: dict[int, dict[str, float]],
    detail_stats: dict[int, dict[str, float]],
    base_fetch_s: float,
    reader_pipeline_s: float,
    required_shuttles: int,
) -> None:
    lines = [
        "# Shuttle Saturation Time Analysis",
        "",
        f"Scope: feeder-buffer + rack3s experiment, batch `{batch_size}`.",
        "",
        "## Per-Glass Timing Model",
        "",
        f"- Average single-shuttle fetch time per glass: `{base_fetch_s:.2f}s`.",
        f"- Average reader pipeline time per glass: `{reader_pipeline_s:.2f}s`.",
        f"- Estimated shuttle count needed to keep reader busy: `ceil({base_fetch_s:.2f} / {reader_pipeline_s:.2f}) = {required_shuttles}`.",
        "",
        "The reader pipeline includes `3s load + read + 3s unload`. In this experiment, average read time is only about "
        f"`{detail_stats[1]['avg_read_s']:.2f}s`, so the reader service interval is dominated by load/unload.",
        "",
        "## Observed Scaling",
        "",
        "| Shuttles | Req/s | Completion min | Reader util | Reader wait/glass s | Buffer wait/glass s | Avg shuttle util |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for shuttle in [1, 2, 4, 8, 16, 32, 64]:
        summary = summary_rows[shuttle]
        detail = detail_stats[shuttle]
        lines.append(
            "| "
            f"{shuttle} | "
            f"{summary['throughput_req_per_s']:.4f} | "
            f"{summary['drive_makespan_s'] / 60.0:.2f} | "
            f"{summary['reader_pipeline_utilization']:.1%} | "
            f"{detail['avg_reader_wait_s']:.2f} | "
            f"{detail['avg_buffer_wait_s']:.2f} | "
            f"{summary['shuttle_utilization_avg']:.1%} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "With 1 shuttle, the shuttle supply interval is much longer than the reader service interval, so the reader waits for glass.",
            "",
            "With 2 shuttles, supply improves but is still not enough to keep the reader continuously busy.",
            "",
            "With 4 shuttles, estimated supply interval becomes shorter than the reader service interval. The reader wait per glass drops to almost zero and reader pipeline utilization reaches about 100%.",
            "",
            "Beyond 4 shuttles, throughput does not improve because the single reader is already saturated. Additional shuttle capacity appears as feeder-buffer waiting, not higher request throughput.",
            "",
            "## Figure",
            "",
            "- `paper_figures/fig6_shuttle_saturation_time_model.pdf`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
