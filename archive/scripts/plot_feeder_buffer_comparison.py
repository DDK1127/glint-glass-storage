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
DIRECT = "#7B8794"
FEEDER = "#2F6B9A"
ORANGE = "#D9822B"


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare no-feeder and feeder-buffer single-reader scaling.")
    parser.add_argument("--direct-dir", default="outputs/single-reader-batch-sweep-64g-synthetic-to64")
    parser.add_argument("--feeder-dir", default="outputs/single-reader-batch-sweep-64g-synthetic-feeder-to64")
    args = parser.parse_args()

    direct_dir = Path(args.direct_dir)
    feeder_dir = Path(args.feeder_dir)
    direct_rows = load_rows(direct_dir / "summary.csv")
    feeder_rows = load_rows(feeder_dir / "summary.csv")
    figures_dir = feeder_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    plot_best_by_batch(direct_rows, feeder_rows, figures_dir)
    plot_batch_10000_lines(direct_rows, feeder_rows, figures_dir)
    plot_feeder_bottleneck(feeder_rows, figures_dir)
    write_analysis(direct_rows, feeder_rows, feeder_dir / "FEEDER_ANALYSIS.md")


def load_rows(path: Path) -> list[dict[str, float]]:
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows.append(
                {
                    "batch_size": float(row["batch_size"]),
                    "shuttle_count": float(row["shuttle_count"]),
                    "request_count": float(row["request_count"]),
                    "service_operation_count": float(row["service_operation_count"]),
                    "drive_makespan_s": float(row["drive_makespan_s"]),
                    "system_drain_s": float(row["system_drain_s"]),
                    "throughput_req_per_s": float(row["throughput_req_per_s"]),
                    "reader_utilization": float(row["reader_utilization"]),
                    "reader_pipeline_utilization": float(row.get("reader_pipeline_utilization") or 0.0),
                    "shuttle_utilization_avg": float(row["shuttle_utilization_avg"]),
                    "reader_waiting_for_glass_s": float(row["reader_waiting_for_glass_s"]),
                    "reader_blocked_by_return_s": float(row["reader_blocked_by_return_s"]),
                    "feeder_buffer_wait_for_slot_s": float(row.get("feeder_buffer_wait_for_slot_s") or 0.0),
                    "feeder_buffer_max_occupancy": float(row.get("feeder_buffer_max_occupancy") or 0.0),
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


def best_by_batch(rows: list[dict[str, float]]) -> list[dict[str, float]]:
    batches = sorted({int(row["batch_size"]) for row in rows})
    return [max((row for row in rows if int(row["batch_size"]) == batch), key=lambda row: row["throughput_req_per_s"]) for batch in batches]


def plot_best_by_batch(
    direct_rows: list[dict[str, float]],
    feeder_rows: list[dict[str, float]],
    figures_dir: Path,
) -> None:
    direct_best = best_by_batch(direct_rows)
    feeder_best = best_by_batch(feeder_rows)
    batches = [int(row["batch_size"]) for row in feeder_best]

    fig, ax = plt.subplots(figsize=(6.8, 3.8))
    ax.plot(batches, [row["throughput_req_per_s"] for row in direct_best], marker="o", color=DIRECT, label="No feeder")
    ax.plot(batches, [row["throughput_req_per_s"] for row in feeder_best], marker="o", color=FEEDER, label="Feeder buffer")
    ax.set_xscale("log")
    ax.set_xlabel("Batch size")
    ax.set_ylabel("Best throughput (requests/s)")
    ax.set_title("Best throughput with and without feeder buffer")
    ax.legend(frameon=False)
    apply_style(ax)
    save(fig, figures_dir, "feeder_vs_direct_best_by_batch")


def plot_batch_10000_lines(
    direct_rows: list[dict[str, float]],
    feeder_rows: list[dict[str, float]],
    figures_dir: Path,
) -> None:
    direct = sorted([row for row in direct_rows if int(row["batch_size"]) == 10000], key=lambda row: row["shuttle_count"])
    feeder = sorted([row for row in feeder_rows if int(row["batch_size"]) == 10000], key=lambda row: row["shuttle_count"])

    fig, ax = plt.subplots(figsize=(7.0, 3.8))
    ax.plot([row["shuttle_count"] for row in direct], [row["throughput_req_per_s"] for row in direct], color=DIRECT, marker="o", markersize=3, label="No feeder")
    ax.plot([row["shuttle_count"] for row in feeder], [row["throughput_req_per_s"] for row in feeder], color=FEEDER, marker="o", markersize=3, label="Feeder buffer")
    ax.set_xlabel("Number of shuttles")
    ax.set_ylabel("Throughput (requests/s)")
    ax.set_title("Batch 10000 shuttle scaling")
    ax.set_xticks([1, 2, 4, 8, 16, 32, 48, 64])
    ax.legend(frameon=False)
    apply_style(ax)
    save(fig, figures_dir, "feeder_vs_direct_batch10000")


def plot_feeder_bottleneck(rows: list[dict[str, float]], figures_dir: Path) -> None:
    selected = [
        row
        for row in rows
        if int(row["batch_size"]) == 10000 and int(row["shuttle_count"]) in {1, 2, 4, 8, 16, 32, 64}
    ]
    selected.sort(key=lambda row: row["shuttle_count"])
    labels = [int(row["shuttle_count"]) for row in selected]
    reader_wait = [row["reader_waiting_for_glass_s"] / 60.0 for row in selected]
    unload = [row["reader_blocked_by_return_s"] / 60.0 for row in selected]
    buffer_wait = [row["feeder_buffer_wait_for_slot_s"] / 60.0 for row in selected]

    fig, ax = plt.subplots(figsize=(7.0, 3.8))
    ax.plot(labels, reader_wait, marker="o", color=FEEDER, label="Reader waits for glass")
    ax.plot(labels, unload, marker="s", color=ORANGE, label="Reader unload time")
    ax.plot(labels, buffer_wait, marker="^", color=DIRECT, label="Fetch waits for buffer slot")
    ax.set_xlabel("Number of shuttles")
    ax.set_ylabel("Accumulated time (minutes)")
    ax.set_title("Feeder-mode bottleneck components, batch 10000")
    ax.set_xticks(labels)
    ax.legend(frameon=False)
    apply_style(ax)
    save(fig, figures_dir, "feeder_bottleneck_batch10000")


def write_analysis(
    direct_rows: list[dict[str, float]],
    feeder_rows: list[dict[str, float]],
    path: Path,
) -> None:
    direct_best = best_by_batch(direct_rows)
    feeder_best = best_by_batch(feeder_rows)
    direct_by_batch = {int(row["batch_size"]): row for row in direct_best}
    feeder_by_batch = {int(row["batch_size"]): row for row in feeder_best}
    lines = [
        "# Feeder Buffer Scaling Analysis",
        "",
        "Input:",
        "",
        "- Same trace, synthetic placement, 64GiB glass, request merge enabled.",
        "- Feeder buffer: 64 slots, shuttle-side place cost 3s, fetch-priority return scheduling.",
        "- Reader load/unload: 3s/3s.",
        "",
        "## Best Throughput Comparison",
        "",
        "| Batch | No-feeder best req/s | Feeder best req/s | Speedup | Feeder best shuttles |",
        "|---:|---:|---:|---:|---:|",
    ]
    for batch in sorted(feeder_by_batch):
        direct = direct_by_batch[batch]
        feeder = feeder_by_batch[batch]
        speedup = feeder["throughput_req_per_s"] / direct["throughput_req_per_s"]
        lines.append(
            "| "
            f"{batch} | "
            f"{direct['throughput_req_per_s']:.4f} | "
            f"{feeder['throughput_req_per_s']:.4f} | "
            f"{speedup:.2f}x | "
            f"{int(feeder['shuttle_count'])} |"
        )

    batch10000 = {
        int(row["shuttle_count"]): row
        for row in feeder_rows
        if int(row["batch_size"]) == 10000
    }
    lines.extend(
        [
            "",
            "## Batch 10000 Feeder Detail",
            "",
            "| Shuttles | Throughput req/s | Completion min | Reader pipeline util | Read-only util | Avg shuttle util | Reader wait min | Buffer-slot wait min |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for shuttle_count in [1, 2, 4, 8, 16, 32, 64]:
        row = batch10000[shuttle_count]
        lines.append(
            "| "
            f"{shuttle_count} | "
            f"{row['throughput_req_per_s']:.4f} | "
            f"{row['drive_makespan_s'] / 60.0:.2f} | "
            f"{row['reader_pipeline_utilization']:.1%} | "
            f"{row['reader_utilization']:.1%} | "
            f"{row['shuttle_utilization_avg']:.1%} | "
            f"{row['reader_waiting_for_glass_s'] / 60.0:.2f} | "
            f"{row['feeder_buffer_wait_for_slot_s'] / 60.0:.2f} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The feeder buffer changes the system from serialized fetch-read-return service into a pipelined service model. "
            "Shuttles can prepare future glass while the reader is reading the current glass.",
            "",
            "Throughput improves sharply with a few shuttles, then saturates early because the single reader's load, read, and unload pipeline becomes the dominant limit.",
            "",
            "## Figures",
            "",
            "- `figures/feeder_vs_direct_best_by_batch.pdf`",
            "- `figures/feeder_vs_direct_batch10000.pdf`",
            "- `figures/feeder_bottleneck_batch10000.pdf`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
