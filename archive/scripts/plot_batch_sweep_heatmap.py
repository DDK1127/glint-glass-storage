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


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot batch-size/shuttle throughput sweep.")
    parser.add_argument("--output-dir", default="outputs/single-reader-batch-sweep-64g-synthetic")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    rows = load_rows(output_dir / "summary.csv")
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    plot_heatmap(rows, figures_dir)
    plot_lines(rows, figures_dir)
    plot_best_by_batch(rows, figures_dir)
    write_analysis(rows, output_dir / "ANALYSIS.md")


def load_rows(path: Path) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows.append(
                {
                    "batch_size": float(row["batch_size"]),
                    "shuttle_count": float(row["shuttle_count"]),
                    "request_count": float(row["request_count"]),
                    "service_operation_count": float(row["service_operation_count"]),
                    "drive_makespan_s": float(row["drive_makespan_s"]),
                    "throughput_req_per_s": float(row["throughput_req_per_s"]),
                    "reader_utilization": float(row["reader_utilization"]),
                    "shuttle_utilization_avg": float(row["shuttle_utilization_avg"]),
                    "saturation_flag": 1.0 if row["saturation_flag"] == "True" else 0.0,
                }
            )
    return rows


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
    fig.savefig(figures_dir / f"{name}.png", dpi=240)
    fig.savefig(figures_dir / f"{name}.pdf")
    plt.close(fig)


def grid(rows: list[dict[str, float]], field: str):
    batches = sorted({int(row["batch_size"]) for row in rows})
    shuttles = sorted({int(row["shuttle_count"]) for row in rows})
    lookup = {(int(row["batch_size"]), int(row["shuttle_count"])): row[field] for row in rows}
    values = [[lookup[(batch, shuttle)] for shuttle in shuttles] for batch in batches]
    return batches, shuttles, values


def plot_heatmap(rows: list[dict[str, float]], figures_dir: Path) -> None:
    batches, shuttles, values = grid(rows, "throughput_req_per_s")
    fig, ax = plt.subplots(figsize=(7.2, 3.9))
    image = ax.imshow(values, aspect="auto", cmap="viridis", origin="lower")
    ax.set_xticks(range(len(shuttles)), shuttles)
    ax.set_yticks(range(len(batches)), batches)
    ax.set_xlabel("Number of shuttles")
    ax.set_ylabel("Batch size")
    ax.set_title("Throughput heatmap: batch size vs. shuttle count")
    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label("Throughput (requests/s)")
    save(fig, figures_dir, "throughput_heatmap")


def plot_lines(rows: list[dict[str, float]], figures_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.0, 3.8))
    batches = sorted({int(row["batch_size"]) for row in rows})
    colors = [BLUE, GREEN, ORANGE, PURPLE, "#7B8794", "#B84A4A", "#2F8132"]
    for batch, color in zip(batches, colors, strict=False):
        series = sorted([row for row in rows if int(row["batch_size"]) == batch], key=lambda row: row["shuttle_count"])
        ax.plot(
            [row["shuttle_count"] for row in series],
            [row["throughput_req_per_s"] for row in series],
            marker="o",
            linewidth=1.7,
            markersize=3.7,
            color=color,
            label=f"{batch}",
        )
    ax.set_xlabel("Number of shuttles")
    ax.set_ylabel("Throughput (requests/s)")
    ax.set_title("Throughput scaling by batch size")
    shuttles = sorted({int(row["shuttle_count"]) for row in rows})
    ax.set_xticks(display_ticks(shuttles))
    ax.legend(title="Batch", frameon=False, fontsize=8, title_fontsize=8, ncol=2)
    apply_style(ax)
    save(fig, figures_dir, "throughput_lines")


def plot_best_by_batch(rows: list[dict[str, float]], figures_dir: Path) -> None:
    batches = sorted({int(row["batch_size"]) for row in rows})
    best = [max((row for row in rows if int(row["batch_size"]) == batch), key=lambda row: row["throughput_req_per_s"]) for batch in batches]

    fig, ax1 = plt.subplots(figsize=(6.6, 3.7))
    ax1.plot(batches, [row["throughput_req_per_s"] for row in best], marker="o", color=BLUE, linewidth=1.9)
    ax1.set_xscale("log")
    ax1.set_xlabel("Batch size")
    ax1.set_ylabel("Best throughput (requests/s)")
    ax1.tick_params(axis="y", colors=BLUE)
    ax1.yaxis.label.set_color(BLUE)

    ax2 = ax1.twinx()
    ax2.plot(batches, [row["service_operation_count"] for row in best], marker="s", color=ORANGE, linewidth=1.7)
    ax2.set_ylabel("Glass service operations")
    ax2.tick_params(axis="y", colors=ORANGE)
    ax2.yaxis.label.set_color(ORANGE)

    for row in best:
        ax1.annotate(
            f"{int(row['shuttle_count'])}S",
            (row["batch_size"], row["throughput_req_per_s"]),
            textcoords="offset points",
            xytext=(0, 7),
            ha="center",
            fontsize=8,
            color=TEXT,
        )
    ax1.set_title("Best throughput and glass moves by batch size")
    apply_style(ax1)
    ax2.spines["top"].set_visible(False)
    ax2.spines["left"].set_visible(False)
    ax2.spines["right"].set_color("#9AA5B1")
    save(fig, figures_dir, "best_by_batch")


def write_analysis(rows: list[dict[str, float]], path: Path) -> None:
    batches = sorted({int(row["batch_size"]) for row in rows})
    shuttles = sorted({int(row["shuttle_count"]) for row in rows})
    batch_list = ", ".join(str(batch) for batch in batches)
    lines = [
        "# Batch Size and Shuttle Count Throughput Sweep",
        "",
        "Input:",
        "",
        "- Glass capacity: `64GiB`",
        "- Placement: synthetic hash over 64MiB logical stripes",
        "- Merge: same-glass requests become one service operation",
        f"- Batch sizes: `{batch_list}`",
        f"- Shuttle counts: `{min(shuttles)}..{max(shuttles)}`",
        "",
        "## Best Throughput By Batch",
        "",
        "| Batch | Best shuttles | Throughput req/s | Completion min | Service ops | Requests/service |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for batch in batches:
        series = [row for row in rows if int(row["batch_size"]) == batch]
        best = max(series, key=lambda row: row["throughput_req_per_s"])
        lines.append(
            "| "
            f"{batch} | "
            f"{int(best['shuttle_count'])} | "
            f"{best['throughput_req_per_s']:.4f} | "
            f"{best['drive_makespan_s'] / 60.0:.2f} | "
            f"{int(best['service_operation_count'])} | "
            f"{best['request_count'] / best['service_operation_count']:.1f} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "Throughput improves with both larger batches and more shuttles, but the curve flattens as shuttle count grows. "
            "Larger batches expose more glass service operations, so additional shuttles have more work to parallelize.",
            "",
            "The heatmap and line plot show whether the experiment is shuttle-limited or reader-gated for each batch size. "
            "If the line flattens early, additional shuttles are no longer the limiting resource under the current direct-service model.",
            "",
            "## Figures",
            "",
            "- `figures/throughput_heatmap.pdf`",
            "- `figures/throughput_lines.pdf`",
            "- `figures/best_by_batch.pdf`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def display_ticks(values: list[int]) -> list[int]:
    if len(values) <= 24:
        return values
    selected = [value for value in values if value in {1, 2, 4, 8, 16, 32, 48, 64}]
    return [value for value in selected if value in set(values)]


if __name__ == "__main__":
    main()
