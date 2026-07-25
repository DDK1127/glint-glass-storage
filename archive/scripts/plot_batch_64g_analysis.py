from __future__ import annotations

import csv
import os
import argparse
import json
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
PURPLE = "#6B5B95"


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot 64GiB batch merge analysis.")
    parser.add_argument("--output-dir", default="outputs/single-reader-batch-merge-scaling-64g-full")
    parser.add_argument("--config", default="configs/single-reader-batch-merge-scaling-64g-full.json")
    parser.add_argument("--title-prefix", default="64GiB glass")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    summary_csv = output_dir / "summary.csv"
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    with Path(args.config).open("r", encoding="utf-8") as handle:
        config = json.load(handle)

    rows = load_summary(summary_csv)
    plot_throughput(rows, figures_dir, args.title_prefix)
    plot_completion(rows, figures_dir)
    plot_merge_collapse(rows, figures_dir)
    plot_hotspot_share(figures_dir, config, args.title_prefix)
    write_analysis(rows, output_dir / "ANALYSIS.md", config)


def load_summary(path: Path) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows.append(
                {
                    "batch_size": float(row["batch_size"]),
                    "shuttle_count": float(row["shuttle_count"]),
                    "request_count": float(row["request_count"]),
                    "service_operation_count": float(row["service_operation_count"]),
                    "merged_request_count": float(row["merged_request_count"]),
                    "drive_makespan_s": float(row["drive_makespan_s"]),
                    "throughput_req_per_s": float(row["throughput_req_per_s"]),
                    "throughput_mib_per_s": float(row["throughput_mib_per_s"]),
                    "reader_utilization": float(row["reader_utilization"]),
                    "saturation_flag": 1.0 if row["saturation_flag"] == "True" else 0.0,
                }
            )
    return rows


def best_by_batch(rows: list[dict[str, float]]) -> list[dict[str, float]]:
    batches = sorted({row["batch_size"] for row in rows})
    return [
        max(
            (row for row in rows if row["batch_size"] == batch),
            key=lambda row: row["throughput_req_per_s"],
        )
        for batch in batches
    ]


def rows_for_shuttles(rows: list[dict[str, float]], shuttles: int) -> list[dict[str, float]]:
    return sorted(
        [row for row in rows if int(row["shuttle_count"]) == shuttles],
        key=lambda row: row["batch_size"],
    )


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


def plot_throughput(rows: list[dict[str, float]], figures_dir: Path, title_prefix: str) -> None:
    fig, ax = plt.subplots(figsize=(6.2, 3.4))
    styles = [(1, BLUE), (2, GREEN), (4, ORANGE), (8, RED), (16, PURPLE)]
    for shuttle_count, color in styles:
        series = rows_for_shuttles(rows, shuttle_count)
        ax.plot(
            [row["batch_size"] for row in series],
            [row["throughput_req_per_s"] for row in series],
            marker="o",
            linewidth=1.8,
            markersize=4,
            color=color,
            label=f"{shuttle_count} shuttles",
        )
    ax.set_xscale("log")
    ax.set_xlabel("Batch size (read requests)")
    ax.set_ylabel("Throughput (requests/s)")
    ax.set_title(f"{title_prefix}: request throughput vs. batch size")
    ax.legend(frameon=False, fontsize=8, ncol=2)
    apply_style(ax)
    save(fig, figures_dir, "throughput_vs_batch")


def plot_completion(rows: list[dict[str, float]], figures_dir: Path) -> None:
    best = best_by_batch(rows)
    fig, ax = plt.subplots(figsize=(6.2, 3.4))
    ax.plot(
        [row["batch_size"] for row in best],
        [row["drive_makespan_s"] / 60.0 for row in best],
        marker="o",
        linewidth=1.9,
        color=BLUE,
    )
    for row in best:
        ax.annotate(
            f"{int(row['shuttle_count'])}S",
            (row["batch_size"], row["drive_makespan_s"] / 60.0),
            textcoords="offset points",
            xytext=(0, 7),
            ha="center",
            fontsize=8,
            color=TEXT,
        )
    ax.set_xscale("log")
    ax.set_xlabel("Batch size (read requests)")
    ax.set_ylabel("Best completion time (min)")
    ax.set_title("Best batch completion time after same-glass merge")
    apply_style(ax)
    save(fig, figures_dir, "completion_time_best")


def plot_merge_collapse(rows: list[dict[str, float]], figures_dir: Path) -> None:
    best = best_by_batch(rows)
    batch_sizes = [row["batch_size"] for row in best]
    service_ops = [row["service_operation_count"] for row in best]
    collapse = [row["request_count"] / row["service_operation_count"] for row in best]

    fig, ax1 = plt.subplots(figsize=(6.2, 3.4))
    ax1.bar(batch_sizes, service_ops, width=[size * 0.18 for size in batch_sizes], color=GREEN, alpha=0.82)
    ax1.set_xscale("log")
    ax1.set_xlabel("Batch size (read requests)")
    ax1.set_ylabel("Glass service operations")
    ax1.tick_params(axis="y", colors=GREEN)
    ax1.yaxis.label.set_color(GREEN)

    ax2 = ax1.twinx()
    ax2.plot(batch_sizes, collapse, marker="s", linewidth=1.8, color=ORANGE)
    ax2.set_ylabel("Requests per glass service")
    ax2.tick_params(axis="y", colors=ORANGE)
    ax2.yaxis.label.set_color(ORANGE)

    ax1.set_title("Same-glass merge collapses many requests into few glass moves")
    apply_style(ax1)
    ax2.spines["top"].set_visible(False)
    ax2.spines["left"].set_visible(False)
    ax2.spines["right"].set_color("#9AA5B1")
    save(fig, figures_dir, "merge_collapse")


def plot_hotspot_share(figures_dir: Path, config: dict, title_prefix: str) -> None:
    shares = compute_hotspot_shares(config)
    fig, ax = plt.subplots(figsize=(6.2, 3.4))
    ax.plot(shares["batch_size"], shares["top1"], marker="o", linewidth=1.8, color=BLUE, label="Top 1 glass")
    ax.plot(shares["batch_size"], shares["top5"], marker="o", linewidth=1.8, color=GREEN, label="Top 5 glass")
    ax.plot(shares["batch_size"], shares["top10"], marker="o", linewidth=1.8, color=ORANGE, label="Top 10 glass")
    ax.set_xscale("log")
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("Batch size (read requests)")
    ax.set_ylabel("Share of requests")
    ax.set_title(f"{title_prefix}: request hotspot concentration")
    ax.legend(frameon=False, fontsize=8)
    apply_style(ax)
    save(fig, figures_dir, "hotspot_share")


def compute_hotspot_shares(config: dict) -> dict[str, list[float]]:
    import collections

    checkpoints = [int(size) for size in config["batch_sizes"]]
    counts: collections.Counter[int] = collections.Counter()
    total = 0
    shares = {"batch_size": [], "top1": [], "top5": [], "top10": []}
    with Path(config["trace_path"]).open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row["IOType"].strip().upper() != "R":
                continue
            total += 1
            counts[platter_id_for_offset(int(row["Offset"]), config["geometry"])] += 1
            if total in checkpoints:
                ranked = counts.most_common()
                shares["batch_size"].append(float(total))
                shares["top1"].append(sum(count for _, count in ranked[:1]) / total)
                shares["top5"].append(sum(count for _, count in ranked[:5]) / total)
                shares["top10"].append(sum(count for _, count in ranked[:10]) / total)
    return shares


def platter_id_for_offset(offset: int, geometry: dict) -> int:
    if geometry.get("placement_mode", "offset") == "offset":
        return offset // int(geometry["platter_capacity_bytes"])
    stripe_id = offset // int(geometry["synthetic_stripe_bytes"])
    hashed = hash_u64(stripe_id ^ int(geometry.get("synthetic_hash_seed", 0)))
    return hashed % int(geometry["synthetic_platter_count"])


def hash_u64(value: int) -> int:
    value &= 0xFFFFFFFFFFFFFFFF
    value ^= value >> 30
    value = (value * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    value ^= value >> 27
    value = (value * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    value ^= value >> 31
    return value


def write_analysis(rows: list[dict[str, float]], path: Path, config: dict) -> None:
    best = best_by_batch(rows)
    geometry = config["geometry"]
    placement_mode = geometry.get("placement_mode", "offset")
    lines = [
        "# Full-Trace 64GiB Same-Glass Merge Analysis",
        "",
        "Input:",
        "",
        "- Trace: `data/2016022211-LUN0.csv`",
        "- Read requests used: up to `1,399,055`",
        "- Glass capacity: `64GiB`",
        f"- Placement mode: `{placement_mode}`",
        "- Merge: same-glass requests in each batch become one glass service operation",
        "- Reader load/unload: `3s / 3s`",
        "",
        "## Best Runs",
        "",
        "| Batch | Best shuttles | Completion min | Throughput req/s | Throughput MiB/s | Service ops | Requests/service | Reader util |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in best:
        lines.append(
            "| "
            f"{int(row['batch_size'])} | "
            f"{int(row['shuttle_count'])} | "
            f"{row['drive_makespan_s'] / 60.0:.2f} | "
            f"{row['throughput_req_per_s']:.3f} | "
            f"{row['throughput_mib_per_s']:.3f} | "
            f"{int(row['service_operation_count'])} | "
            f"{row['request_count'] / row['service_operation_count']:.1f} | "
            f"{row['reader_utilization']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "Increasing the trace length reinforces the hotspot/locality behavior. "
            "The number of glass service operations depends strongly on placement policy.",
            "",
            "This is a useful batching result, but it is not a shuttle-scaling stress test. "
            "With this mapping, the workload mostly stresses same-glass batching and reader-side service, "
            "not broad robotic movement across many glass platters.",
            "",
            "## Figures",
            "",
            "- `figures/throughput_vs_batch.pdf`",
            "- `figures/completion_time_best.pdf`",
            "- `figures/merge_collapse.pdf`",
            "- `figures/hotspot_share.pdf`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
