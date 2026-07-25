from __future__ import annotations

import argparse
import csv
import json
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
GREEN = "#4C9F70"
ORANGE = "#D9822B"
PURPLE = "#6B5B95"
GRAY = "#7B8794"


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot per-glass reader access vs rack-to-feeder fetch time.")
    parser.add_argument("--output-dir", default="outputs/single-reader-large-batch-64g-synthetic-feeder-rack3s-to64")
    parser.add_argument("--batch-size", type=int, default=500000)
    parser.add_argument("--shuttle-count", type=int, default=1)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    config = json.loads((output_dir / "config.json").read_text(encoding="utf-8"))
    detail_path = output_dir / f"batch_{args.batch_size:05d}" / f"shuttles_{args.shuttle_count:02d}" / "request_detail.csv"
    stats = compute_stats(detail_path, config)

    figures_dir = output_dir / "paper_figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    plot_ratio(stats, figures_dir)
    write_markdown(stats, output_dir / "PER_GLASS_TIME_RATIO.md")


def compute_stats(detail_path: Path, config: dict) -> dict[str, float]:
    timing = config["timing"]
    service_ops = 0
    fetch_total_s = 0.0
    reader_read_s = 0.0

    with detail_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            service_ops += 1
            fetch_total_s += float(row["fetch_s"]) - float(row["feeder_buffer_wait_for_slot_s"])
            reader_read_s += float(row["read_s"])

    avg_fetch_total_s = fetch_total_s / service_ops
    avg_reader_read_s = reader_read_s / service_ops
    avg_reader_load_s = float(timing["reader_load_s"])
    avg_reader_unload_s = float(timing["reader_unload_s"])
    avg_reader_pipeline_s = avg_reader_load_s + avg_reader_read_s + avg_reader_unload_s

    avg_fetch_move_s = avg_fetch_total_s - float(timing["storage_pick_s"]) - float(config["feeder_buffer"]["shuttle_place_s"])
    avg_fetch_move_s = max(avg_fetch_move_s, 0.0)
    ratio = avg_fetch_total_s / avg_reader_pipeline_s

    return {
        "service_ops": float(service_ops),
        "reader_load_s": avg_reader_load_s,
        "reader_read_s": avg_reader_read_s,
        "reader_unload_s": avg_reader_unload_s,
        "reader_pipeline_s": avg_reader_pipeline_s,
        "fetch_move_s": avg_fetch_move_s,
        "fetch_pick_s": float(timing["storage_pick_s"]),
        "fetch_place_feeder_s": float(config["feeder_buffer"]["shuttle_place_s"]),
        "fetch_total_s": avg_fetch_total_s,
        "fetch_to_reader_ratio": ratio,
        "estimated_shuttles_to_saturate": float(math.ceil(ratio)),
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


def plot_ratio(stats: dict[str, float], figures_dir: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.8), gridspec_kw={"width_ratios": [1.25, 1.0]})

    ax = axes[0]
    reader_parts = [
        ("Load", stats["reader_load_s"], BLUE),
        ("Read", stats["reader_read_s"], GREEN),
        ("Unload", stats["reader_unload_s"], ORANGE),
    ]
    fetch_parts = [
        ("Move", stats["fetch_move_s"], PURPLE),
        ("Pick", stats["fetch_pick_s"], BLUE),
        ("Place", stats["fetch_place_feeder_s"], GRAY),
    ]
    bottom = 0.0
    for label, value, color in reader_parts:
        ax.bar("Reader access", value, bottom=bottom, color=color, label=f"Reader {label}")
        bottom += value
    bottom = 0.0
    for label, value, color in fetch_parts:
        ax.bar("Rack to feeder", value, bottom=bottom, color=color, alpha=0.88, label=f"Fetch {label}")
        bottom += value
    ax.set_ylabel("Average seconds per glass")
    ax.set_title("Per-glass time components")
    ax.legend(frameon=False, fontsize=7, ncol=2)
    apply_style(ax)

    ax = axes[1]
    values = [stats["reader_pipeline_s"], stats["fetch_total_s"]]
    ax.bar(["Reader", "Rack→feeder"], values, color=[ORANGE, PURPLE])
    ax.set_ylabel("Average seconds per glass")
    ax.set_title(f"Fetch / reader = {stats['fetch_to_reader_ratio']:.2f}x")
    for index, value in enumerate(values):
        ax.text(index, value + 0.4, f"{value:.2f}s", ha="center", va="bottom", fontsize=9, color=TEXT)
    ax.text(
        0.5,
        max(values) * 0.56,
        f"ceil({stats['fetch_total_s']:.2f} / {stats['reader_pipeline_s']:.2f})\n= {int(stats['estimated_shuttles_to_saturate'])} shuttles",
        ha="center",
        va="center",
        fontsize=9,
        color=TEXT,
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "edgecolor": GRID},
    )
    apply_style(ax)

    fig.tight_layout()
    fig.savefig(figures_dir / "fig7_per_glass_time_ratio.pdf")
    fig.savefig(figures_dir / "fig7_per_glass_time_ratio.png", dpi=300)
    plt.close(fig)


def write_markdown(stats: dict[str, float], path: Path) -> None:
    lines = [
        "# Per-Glass Time Ratio",
        "",
        "Scope: batch 500k, feeder-buffer architecture, rack pick/place 3s, reader load/unload 3s.",
        "",
        "| Component | Avg seconds/glass |",
        "|---|---:|",
        f"| Reader load | {stats['reader_load_s']:.2f} |",
        f"| Reader read | {stats['reader_read_s']:.2f} |",
        f"| Reader unload | {stats['reader_unload_s']:.2f} |",
        f"| Reader total | {stats['reader_pipeline_s']:.2f} |",
        f"| Rack-to-feeder move | {stats['fetch_move_s']:.2f} |",
        f"| Rack pick | {stats['fetch_pick_s']:.2f} |",
        f"| Feeder place | {stats['fetch_place_feeder_s']:.2f} |",
        f"| Rack-to-feeder total | {stats['fetch_total_s']:.2f} |",
        "",
        "## Interpretation",
        "",
        f"Moving one glass from rack to feeder takes `{stats['fetch_to_reader_ratio']:.2f}x` as long as one reader access pipeline.",
        "",
        f"That implies roughly `ceil({stats['fetch_total_s']:.2f} / {stats['reader_pipeline_s']:.2f}) = {int(stats['estimated_shuttles_to_saturate'])}` shuttles are needed to keep one reader saturated.",
        "",
        "This is why the system is shuttle-bound below about 4 shuttles and reader-bound once 4 shuttles can keep the feeder supplied.",
        "",
        "## Figure",
        "",
        "- `paper_figures/fig7_per_glass_time_ratio.pdf`",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
