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
RED = "#B84A4A"


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot fixed-batch shuttle scaling.")
    parser.add_argument("--output-dir", default="outputs/single-reader-10k-64g-synthetic")
    parser.add_argument("--title", default="Batch 10k, 64GiB synthetic placement")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    rows = load_rows(output_dir / "summary.csv")
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    plot_scaling(rows, figures_dir, args.title)
    plot_bottleneck(rows, figures_dir, args.title)
    write_analysis(rows, output_dir / "ANALYSIS.md")


def load_rows(path: Path) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows.append(
                {
                    "shuttle_count": float(row["shuttle_count"]),
                    "request_count": float(row["request_count"]),
                    "service_operation_count": float(row["service_operation_count"]),
                    "merged_request_count": float(row["merged_request_count"]),
                    "drive_makespan_s": float(row["drive_makespan_s"]),
                    "throughput_req_per_s": float(row["throughput_req_per_s"]),
                    "throughput_mib_per_s": float(row["throughput_mib_per_s"]),
                    "reader_utilization": float(row["reader_utilization"]),
                    "shuttle_utilization_avg": float(row["shuttle_utilization_avg"]),
                    "shuttle_utilization_max": float(row["shuttle_utilization_max"]),
                    "latency_p95_s": float(row["latency_p95_s"]),
                    "reader_waiting_for_glass_s": float(row["reader_waiting_for_glass_s"]),
                    "reader_blocked_by_return_s": float(row["reader_blocked_by_return_s"]),
                    "saturation_flag": 1.0 if row["saturation_flag"] == "True" else 0.0,
                }
            )
    return sorted(rows, key=lambda row: row["shuttle_count"])


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


def plot_scaling(rows: list[dict[str, float]], figures_dir: Path, title: str) -> None:
    shuttles = [row["shuttle_count"] for row in rows]
    throughput = [row["throughput_req_per_s"] for row in rows]
    completion_min = [row["drive_makespan_s"] / 60.0 for row in rows]

    fig, ax1 = plt.subplots(figsize=(6.4, 3.6))
    ax1.plot(shuttles, throughput, marker="o", linewidth=2.0, color=BLUE, label="Throughput")
    ax1.set_xlabel("Number of shuttles")
    ax1.set_ylabel("Throughput (requests/s)")
    ax1.tick_params(axis="y", colors=BLUE)
    ax1.yaxis.label.set_color(BLUE)
    ax1.set_xticks(shuttles)

    ax2 = ax1.twinx()
    ax2.plot(shuttles, completion_min, marker="s", linewidth=1.8, color=ORANGE, label="Completion")
    ax2.set_ylabel("Completion time (min)")
    ax2.tick_params(axis="y", colors=ORANGE)
    ax2.yaxis.label.set_color(ORANGE)

    sat = next((row for row in rows if row["saturation_flag"]), None)
    if sat:
        ax1.axvline(sat["shuttle_count"], color=RED, linestyle="--", linewidth=1.2)
        ax1.text(
            sat["shuttle_count"] + 0.15,
            max(throughput) * 0.72,
            f"<5% gain at {int(sat['shuttle_count'])} shuttles",
            color=RED,
            fontsize=8,
            rotation=90,
            va="center",
        )

    ax1.set_title(f"{title}: shuttle scaling")
    apply_style(ax1)
    ax2.spines["top"].set_visible(False)
    ax2.spines["left"].set_visible(False)
    ax2.spines["right"].set_color("#9AA5B1")
    save(fig, figures_dir, "shuttle_scaling")


def plot_bottleneck(rows: list[dict[str, float]], figures_dir: Path, title: str) -> None:
    selected = [row for row in rows if int(row["shuttle_count"]) in {1, 2, 4, 8, 16}]
    labels = [f"{int(row['shuttle_count'])}" for row in selected]
    wait_per_req = [row["reader_waiting_for_glass_s"] / row["service_operation_count"] for row in selected]
    return_block_per_req = [row["reader_blocked_by_return_s"] / row["service_operation_count"] for row in selected]

    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    x = range(len(selected))
    ax.bar(x, wait_per_req, color=GREEN, width=0.58, label="Waiting for glass")
    ax.bar(x, return_block_per_req, bottom=wait_per_req, color=ORANGE, width=0.58, label="Blocked by unload")
    ax.set_xticks(list(x), labels)
    ax.set_xlabel("Number of shuttles")
    ax.set_ylabel("Average reader-side delay per glass service (s)")
    ax.set_title(f"{title}: reader-side delay breakdown")
    ax.legend(frameon=False, fontsize=8)
    apply_style(ax)
    save(fig, figures_dir, "reader_delay_breakdown")


def write_analysis(rows: list[dict[str, float]], path: Path) -> None:
    best = max(rows, key=lambda row: row["throughput_req_per_s"])
    sat = next((row for row in rows if row["saturation_flag"]), None)
    lines = [
        "# Fixed Batch Shuttle Scaling Analysis",
        "",
        "Input:",
        "",
        "- Batch size: `10000` read requests",
        "- Glass capacity: `64GiB`",
        "- Placement: synthetic hash over 64MiB logical stripes",
        "- Merge: same-glass requests become one service operation",
        "- Shuttle sweep: `1..16`",
        "",
        "## Summary",
        "",
        f"- Original requests: `{int(best['request_count'])}`",
        f"- Glass service operations after merge: `{int(best['service_operation_count'])}`",
        f"- Requests merged: `{int(best['merged_request_count'])}`",
        f"- Best throughput: `{best['throughput_req_per_s']:.4f} req/s` at `{int(best['shuttle_count'])}` shuttles",
        f"- Best completion time: `{best['drive_makespan_s'] / 60.0:.2f} min`",
    ]
    if sat:
        lines.append(f"- First `<5%` marginal-gain point: `{int(sat['shuttle_count'])}` shuttles")
    lines.extend(
        [
            "",
            "## Shuttle Sweep",
            "",
            "| Shuttles | Throughput req/s | Completion min | Reader util | Avg shuttle util | P95 latency min |",
            "|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in rows:
        lines.append(
            "| "
            f"{int(row['shuttle_count'])} | "
            f"{row['throughput_req_per_s']:.4f} | "
            f"{row['drive_makespan_s'] / 60.0:.2f} | "
            f"{row['reader_utilization']:.3f} | "
            f"{row['shuttle_utilization_avg']:.3f} | "
            f"{row['latency_p95_s'] / 60.0:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "Synthetic placement makes the 10k batch touch far more glass than direct 64GiB offset mapping. "
            "That makes shuttle count matter again: throughput increases steadily from 1 to 16 shuttles, "
            "while the first strict `<5%` marginal gain appears around the middle of the sweep.",
            "",
            "The reader is still mostly waiting for glass rather than reading data. This indicates the current "
            "reader-gated direct-service model remains dominated by mechanical delivery, not reader bandwidth.",
            "",
            "## Figures",
            "",
            "- `figures/shuttle_scaling.pdf`",
            "- `figures/reader_delay_breakdown.pdf`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
