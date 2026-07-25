from __future__ import annotations

import argparse
import csv
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
GREEN = "#4C9F70"
ORANGE = "#D9822B"
PURPLE = "#6B5B95"
RED = "#B84A4A"
GRAY = "#7B8794"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate paper-style figures for large-batch feeder sweep.")
    parser.add_argument("--output-dir", default="outputs/single-reader-large-batch-64g-synthetic-feeder-rack3s-to64")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    rows = load_rows(output_dir / "summary.csv")
    paper_dir = output_dir / "paper_figures"
    paper_dir.mkdir(parents=True, exist_ok=True)

    metrics = build_metrics(rows)
    write_metrics_csv(metrics, output_dir / "paper_metrics.csv")
    plot_request_throughput(rows, paper_dir)
    plot_glass_service_throughput(rows, paper_dir)
    plot_batch_amplification(metrics, paper_dir)
    plot_saturation_summary(metrics, paper_dir)
    plot_combined_panel(rows, metrics, paper_dir)
    write_analysis(metrics, output_dir / "PAPER_ANALYSIS.md")


def load_rows(path: Path) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            parsed = {
                "batch_size": float(row["batch_size"]),
                "shuttle_count": float(row["shuttle_count"]),
                "request_count": float(row["request_count"]),
                "service_operation_count": float(row["service_operation_count"]),
                "merged_request_count": float(row["merged_request_count"]),
                "drive_makespan_s": float(row["drive_makespan_s"]),
                "system_drain_s": float(row["system_drain_s"]),
                "throughput_req_per_s": float(row["throughput_req_per_s"]),
                "throughput_mib_per_s": float(row["throughput_mib_per_s"]),
                "reader_pipeline_utilization": float(row["reader_pipeline_utilization"]),
                "shuttle_utilization_avg": float(row["shuttle_utilization_avg"]),
                "reader_waiting_for_glass_s": float(row["reader_waiting_for_glass_s"]),
                "feeder_buffer_wait_for_slot_s": float(row["feeder_buffer_wait_for_slot_s"]),
                "saturation_flag": 1.0 if row["saturation_flag"] == "True" else 0.0,
            }
            parsed["glass_ops_per_s"] = parsed["service_operation_count"] / parsed["drive_makespan_s"]
            parsed["requests_per_service"] = parsed["request_count"] / parsed["service_operation_count"]
            rows.append(parsed)
    return rows


def build_metrics(rows: list[dict[str, float]]) -> list[dict[str, float]]:
    metrics = []
    for batch in sorted({int(row["batch_size"]) for row in rows}):
        series = sorted([row for row in rows if int(row["batch_size"]) == batch], key=lambda row: row["shuttle_count"])
        best = max(series, key=lambda row: row["throughput_req_per_s"])
        sat = next((row for row in series if row["saturation_flag"] == 1.0), None)
        row1 = next(row for row in series if int(row["shuttle_count"]) == 1)
        row2 = next(row for row in series if int(row["shuttle_count"]) == 2)
        row4 = next(row for row in series if int(row["shuttle_count"]) == 4)
        row64 = next(row for row in series if int(row["shuttle_count"]) == 64)
        metrics.append(
            {
                "batch_size": float(batch),
                "service_operation_count": best["service_operation_count"],
                "merged_request_count": best["merged_request_count"],
                "requests_per_service": best["requests_per_service"],
                "best_shuttle_count": best["shuttle_count"],
                "saturation_shuttle_count": sat["shuttle_count"] if sat else 0.0,
                "best_throughput_req_per_s": best["throughput_req_per_s"],
                "best_glass_ops_per_s": best["glass_ops_per_s"],
                "completion_min": best["drive_makespan_s"] / 60.0,
                "system_drain_min": best["system_drain_s"] / 60.0,
                "reader_pipeline_utilization": best["reader_pipeline_utilization"],
                "gain_1_to_2_pct": percent_gain(row1["throughput_req_per_s"], row2["throughput_req_per_s"]),
                "gain_2_to_4_pct": percent_gain(row2["throughput_req_per_s"], row4["throughput_req_per_s"]),
                "gain_4_to_64_pct": percent_gain(row4["throughput_req_per_s"], row64["throughput_req_per_s"]),
            }
        )
    return metrics


def percent_gain(old: float, new: float) -> float:
    if old == 0:
        return 0.0
    return (new / old - 1.0) * 100.0


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


def save(fig, output_dir: Path, name: str) -> None:
    fig.tight_layout()
    fig.savefig(output_dir / f"{name}.pdf")
    fig.savefig(output_dir / f"{name}.png", dpi=300)
    plt.close(fig)


def color_for_batches(batches: list[int]) -> dict[int, tuple[float, float, float, float]]:
    cmap = plt.get_cmap("viridis")
    if len(batches) == 1:
        return {batches[0]: cmap(0.6)}
    return {batch: cmap(index / (len(batches) - 1)) for index, batch in enumerate(batches)}


def plot_request_throughput(rows: list[dict[str, float]], output_dir: Path) -> None:
    batches = sorted({int(row["batch_size"]) for row in rows})
    colors = color_for_batches(batches)
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    for batch in batches:
        series = sorted([row for row in rows if int(row["batch_size"]) == batch], key=lambda row: row["shuttle_count"])
        ax.plot(
            [row["shuttle_count"] for row in series],
            [row["throughput_req_per_s"] for row in series],
            marker="o",
            markersize=3.0,
            linewidth=1.8,
            color=colors[batch],
            label=f"{batch // 1000}k",
        )
    ax.set_xscale("log", base=2)
    ax.set_xticks([1, 2, 4, 8, 16, 32, 64], [1, 2, 4, 8, 16, 32, 64])
    ax.set_xlabel("Number of shuttles")
    ax.set_ylabel("Request throughput (req/s)")
    ax.set_title("Request throughput scales with batch size, not beyond 4 shuttles")
    ax.legend(title="Batch", frameon=False, fontsize=8, title_fontsize=8, ncol=2)
    apply_style(ax)
    save(fig, output_dir, "fig1_request_throughput_vs_shuttles")


def plot_glass_service_throughput(rows: list[dict[str, float]], output_dir: Path) -> None:
    batches = sorted({int(row["batch_size"]) for row in rows})
    colors = color_for_batches(batches)
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    for batch in batches:
        series = sorted([row for row in rows if int(row["batch_size"]) == batch], key=lambda row: row["shuttle_count"])
        ax.plot(
            [row["shuttle_count"] for row in series],
            [row["glass_ops_per_s"] for row in series],
            marker="o",
            markersize=3.0,
            linewidth=1.8,
            color=colors[batch],
            label=f"{batch // 1000}k",
        )
    ax.set_xscale("log", base=2)
    ax.set_xticks([1, 2, 4, 8, 16, 32, 64], [1, 2, 4, 8, 16, 32, 64])
    ax.set_xlabel("Number of shuttles")
    ax.set_ylabel("Glass service throughput (ops/s)")
    ax.set_title("Physical glass-service rate saturates at the single reader")
    ax.legend(title="Batch", frameon=False, fontsize=8, title_fontsize=8, ncol=2)
    apply_style(ax)
    save(fig, output_dir, "fig2_glass_ops_vs_shuttles")


def plot_batch_amplification(metrics: list[dict[str, float]], output_dir: Path) -> None:
    batches = [row["batch_size"] for row in metrics]
    fig, ax1 = plt.subplots(figsize=(7.0, 4.0))
    ax1.plot(batches, [row["best_throughput_req_per_s"] for row in metrics], marker="o", color=BLUE, linewidth=2.0)
    ax1.set_xscale("log")
    ax1.set_xlabel("Batch size")
    ax1.set_ylabel("Best request throughput (req/s)", color=BLUE)
    ax1.tick_params(axis="y", colors=BLUE)

    ax2 = ax1.twinx()
    ax2.plot(batches, [row["requests_per_service"] for row in metrics], marker="s", color=ORANGE, linewidth=1.9)
    ax2.set_ylabel("Requests per glass service", color=ORANGE)
    ax2.tick_params(axis="y", colors=ORANGE)
    ax1.set_title("Larger batches increase throughput through merge amplification")
    apply_style(ax1)
    ax2.spines["top"].set_visible(False)
    ax2.spines["left"].set_visible(False)
    ax2.spines["right"].set_color("#9AA5B1")
    save(fig, output_dir, "fig3_batch_merge_amplification")


def plot_saturation_summary(metrics: list[dict[str, float]], output_dir: Path) -> None:
    batches = [row["batch_size"] for row in metrics]
    fig, ax = plt.subplots(figsize=(7.0, 3.8))
    ax.plot(batches, [row["best_shuttle_count"] for row in metrics], marker="o", color=PURPLE, label="Best shuttle count")
    ax.plot(
        batches,
        [row["saturation_shuttle_count"] for row in metrics],
        marker="s",
        color=GRAY,
        label="First <5% marginal gain",
    )
    ax.set_xscale("log")
    ax.set_yticks([1, 2, 4, 5, 8, 16, 32, 64])
    ax.set_xlabel("Batch size")
    ax.set_ylabel("Shuttle count")
    ax.set_title("Feeder-buffer design saturates at a small shuttle count")
    ax.legend(frameon=False)
    apply_style(ax)
    save(fig, output_dir, "fig4_saturation_summary")


def plot_combined_panel(rows: list[dict[str, float]], metrics: list[dict[str, float]], output_dir: Path) -> None:
    batches = sorted({int(row["batch_size"]) for row in rows})
    colors = color_for_batches(batches)
    fig, axes = plt.subplots(2, 2, figsize=(9.5, 6.4))
    ax = axes[0][0]
    for batch in batches:
        series = sorted([row for row in rows if int(row["batch_size"]) == batch], key=lambda row: row["shuttle_count"])
        ax.plot(
            [row["shuttle_count"] for row in series],
            [row["throughput_req_per_s"] for row in series],
            marker="o",
            markersize=2.5,
            linewidth=1.5,
            color=colors[batch],
            label=f"{batch // 1000}k",
        )
    ax.set_xscale("log", base=2)
    ax.set_xticks([1, 2, 4, 8, 16, 32, 64], [1, 2, 4, 8, 16, 32, 64])
    ax.set_xlabel("Shuttles")
    ax.set_ylabel("Req/s")
    ax.set_title("(a) Request throughput")
    apply_style(ax)

    ax = axes[0][1]
    for batch in batches:
        series = sorted([row for row in rows if int(row["batch_size"]) == batch], key=lambda row: row["shuttle_count"])
        ax.plot(
            [row["shuttle_count"] for row in series],
            [row["glass_ops_per_s"] for row in series],
            marker="o",
            markersize=2.5,
            linewidth=1.5,
            color=colors[batch],
        )
    ax.set_xscale("log", base=2)
    ax.set_xticks([1, 2, 4, 8, 16, 32, 64], [1, 2, 4, 8, 16, 32, 64])
    ax.set_xlabel("Shuttles")
    ax.set_ylabel("Glass ops/s")
    ax.set_title("(b) Glass service rate")
    apply_style(ax)

    ax = axes[1][0]
    metric_batches = [row["batch_size"] for row in metrics]
    ax.plot(metric_batches, [row["best_throughput_req_per_s"] for row in metrics], marker="o", color=BLUE, label="Req/s")
    ax2 = ax.twinx()
    ax2.plot(metric_batches, [row["requests_per_service"] for row in metrics], marker="s", color=ORANGE, label="Req/service")
    ax.set_xscale("log")
    ax.set_xlabel("Batch size")
    ax.set_ylabel("Best req/s", color=BLUE)
    ax2.set_ylabel("Req/service", color=ORANGE)
    ax.tick_params(axis="y", colors=BLUE)
    ax2.tick_params(axis="y", colors=ORANGE)
    ax.set_title("(c) Merge amplification")
    apply_style(ax)
    ax2.spines["top"].set_visible(False)
    ax2.spines["left"].set_visible(False)
    ax2.spines["right"].set_color("#9AA5B1")

    ax = axes[1][1]
    ax.plot(metric_batches, [row["best_shuttle_count"] for row in metrics], marker="o", color=PURPLE, label="Best")
    ax.plot(metric_batches, [row["saturation_shuttle_count"] for row in metrics], marker="s", color=GRAY, label="First <5%")
    ax.set_xscale("log")
    ax.set_yticks([1, 2, 4, 5, 8, 16, 32, 64])
    ax.set_xlabel("Batch size")
    ax.set_ylabel("Shuttle count")
    ax.set_title("(d) Saturation point")
    ax.legend(frameon=False, fontsize=8)
    apply_style(ax)

    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, title="Batch", loc="upper center", ncol=7, frameon=False, fontsize=8, title_fontsize=8)
    fig.subplots_adjust(top=0.88)
    save(fig, output_dir, "fig5_combined_paper_panel")


def write_metrics_csv(metrics: list[dict[str, float]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(metrics[0].keys()) if metrics else []
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in metrics:
            writer.writerow(row)


def write_analysis(metrics: list[dict[str, float]], path: Path) -> None:
    best = max(metrics, key=lambda row: row["best_throughput_req_per_s"])
    first = metrics[0]
    last = metrics[-1]
    median_glass_ops = sorted(row["best_glass_ops_per_s"] for row in metrics)[len(metrics) // 2]
    lines = [
        "# Paper-Style Batch Size and Shuttle Scaling Analysis",
        "",
        "Experiment: single reader, feeder buffer enabled, 64GiB glass, synthetic placement, rack pick/place 3s, reader load/unload 3s, request merge enabled.",
        "",
        "## Main Results",
        "",
        "| Batch | Service ops | Req/service | Best shuttles | Best req/s | Glass ops/s | Completion min | Reader pipeline util | 4S->64S gain |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in metrics:
        lines.append(
            "| "
            f"{int(row['batch_size'])} | "
            f"{int(row['service_operation_count'])} | "
            f"{row['requests_per_service']:.1f} | "
            f"{int(row['best_shuttle_count'])} | "
            f"{row['best_throughput_req_per_s']:.4f} | "
            f"{row['best_glass_ops_per_s']:.4f} | "
            f"{row['completion_min']:.2f} | "
            f"{row['reader_pipeline_utilization']:.1%} | "
            f"{row['gain_4_to_64_pct']:.2f}% |"
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            f"Request throughput increases from `{first['best_throughput_req_per_s']:.4f}` req/s at batch {int(first['batch_size'])} to `{last['best_throughput_req_per_s']:.4f}` req/s at batch {int(last['batch_size'])}.",
            "",
            f"This increase is caused by merge amplification: requests per glass service rise from `{first['requests_per_service']:.1f}` to `{last['requests_per_service']:.1f}`.",
            "",
            f"The underlying physical glass-service throughput is nearly constant once the reader is saturated, around `{median_glass_ops:.4f}` glass services/s.",
            "",
            "Across all tested batch sizes, the best shuttle count remains `4`. Additional shuttles do not improve drive throughput because the feeder buffer already keeps the single reader supplied.",
            "",
            f"The largest measured throughput is `{best['best_throughput_req_per_s']:.4f}` req/s at batch `{int(best['batch_size'])}` with `{int(best['best_shuttle_count'])}` shuttles.",
            "",
            "For paper wording, separate logical request throughput from physical glass-service throughput: larger batches improve logical throughput by coalescing more requests per fetched glass, while the reader-side pipeline caps glass services/s.",
            "",
            "## Figure Set",
            "",
            "- `paper_figures/fig1_request_throughput_vs_shuttles.pdf`",
            "- `paper_figures/fig2_glass_ops_vs_shuttles.pdf`",
            "- `paper_figures/fig3_batch_merge_amplification.pdf`",
            "- `paper_figures/fig4_saturation_summary.pdf`",
            "- `paper_figures/fig5_combined_paper_panel.pdf`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
