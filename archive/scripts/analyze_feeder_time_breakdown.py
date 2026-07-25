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
RED = "#B84A4A"
MIB = 1024 * 1024


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze feeder-buffer time bottlenecks.")
    parser.add_argument("--output-dir", default="outputs/single-reader-batch-sweep-64g-synthetic-feeder-to64")
    parser.add_argument("--batch-size", type=int, default=10000)
    parser.add_argument("--shuttles", default="1,2,4,8,16,32,64")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    shuttle_counts = [int(value) for value in args.shuttles.split(",") if value.strip()]
    config = json.loads((output_dir / "config.json").read_text(encoding="utf-8"))
    summary_rows = load_summary(output_dir / "summary.csv")
    breakdowns = [
        build_breakdown(output_dir, config, summary_rows, args.batch_size, shuttle_count)
        for shuttle_count in shuttle_counts
    ]

    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    plot_reader_breakdown(breakdowns, figures_dir)
    plot_fetch_breakdown(breakdowns, figures_dir)
    write_markdown(breakdowns, output_dir / "TIME_BREAKDOWN.md", args.batch_size)


def load_summary(path: Path) -> dict[tuple[int, int], dict[str, str]]:
    rows = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows[(int(row["batch_size"]), int(row["shuttle_count"]))] = row
    return rows


def build_breakdown(
    output_dir: Path,
    config: dict,
    summary_rows: dict[tuple[int, int], dict[str, str]],
    batch_size: int,
    shuttle_count: int,
) -> dict[str, float]:
    detail_path = output_dir / f"batch_{batch_size:05d}" / f"shuttles_{shuttle_count:02d}" / "request_detail.csv"
    summary = summary_rows[(batch_size, shuttle_count)]
    geometry = config["geometry"]
    movement = config["movement"]
    timing = config["timing"]
    feeder = config["feeder_buffer"]
    conflict_penalty_s = config["conflict_penalty"]["penalty_s"]

    ops = 0
    request_count = 0
    fetch_move_to_glass_s = 0.0
    fetch_move_to_buffer_s = 0.0
    fetch_pick_s = 0.0
    fetch_place_buffer_s = 0.0
    fetch_conflict_s = 0.0
    fetch_total_s = 0.0
    feeder_slot_wait_s = 0.0
    reader_load_s = 0.0
    reader_read_s = 0.0
    reader_unload_s = 0.0
    reader_wait_s = 0.0
    return_total_s = 0.0
    return_move_and_place_s = 0.0
    return_conflict_s = 0.0
    read_bytes = 0

    with detail_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            ops += 1
            request_count += int(row["merged_request_count"])
            level = int(row["level"])
            slot = int(row["slot"])
            move_to_glass_s = move_time_s(geometry, movement, geometry["reader_level"], geometry["reader_slot"], level, slot)
            move_to_buffer_s = move_time_s(geometry, movement, level, slot, geometry["reader_level"], geometry["reader_slot"])
            fetch_move_to_glass_s += move_to_glass_s
            fetch_move_to_buffer_s += move_to_buffer_s
            fetch_pick_s += timing["storage_pick_s"]
            fetch_place_buffer_s += feeder["shuttle_place_s"]
            fetch_conflict_s += int(row["fetch_conflict_count"]) * conflict_penalty_s
            fetch_total_s += float(row["fetch_s"])
            feeder_slot_wait_s += float(row["feeder_buffer_wait_for_slot_s"])
            reader_load_s += timing["reader_load_s"]
            reader_read_s += float(row["read_s"])
            reader_unload_s += float(row["reader_blocked_by_return_s"])
            reader_wait_s += float(row["reader_waiting_for_glass_s"])
            return_s = float(row["return_done_s"]) - float(row["return_start_s"])
            return_total_s += return_s
            return_conflict = int(row["return_conflict_count"]) * conflict_penalty_s
            return_conflict_s += return_conflict
            return_move_and_place_s += max(0.0, return_s - return_conflict)
            read_bytes += int(row["size_bytes"])

    drive_makespan_s = float(summary["drive_makespan_s"])
    system_drain_s = float(summary["system_drain_s"])
    reader_pipeline_s = reader_load_s + reader_read_s + reader_unload_s
    fetch_accounted_s = (
        fetch_move_to_glass_s
        + fetch_pick_s
        + fetch_move_to_buffer_s
        + fetch_place_buffer_s
        + feeder_slot_wait_s
        + fetch_conflict_s
    )

    return {
        "batch_size": float(batch_size),
        "shuttle_count": float(shuttle_count),
        "request_count": float(request_count),
        "service_ops": float(ops),
        "throughput_req_per_s": float(summary["throughput_req_per_s"]),
        "drive_makespan_s": drive_makespan_s,
        "system_drain_s": system_drain_s,
        "reader_pipeline_s": reader_pipeline_s,
        "reader_load_s": reader_load_s,
        "reader_read_s": reader_read_s,
        "reader_unload_s": reader_unload_s,
        "reader_wait_s": reader_wait_s,
        "reader_pipeline_utilization": float(summary["reader_pipeline_utilization"]),
        "fetch_total_s": fetch_total_s,
        "fetch_move_to_glass_s": fetch_move_to_glass_s,
        "fetch_pick_s": fetch_pick_s,
        "fetch_move_to_buffer_s": fetch_move_to_buffer_s,
        "fetch_place_buffer_s": fetch_place_buffer_s,
        "feeder_slot_wait_s": feeder_slot_wait_s,
        "fetch_conflict_s": fetch_conflict_s,
        "fetch_accounted_s": fetch_accounted_s,
        "return_total_s": return_total_s,
        "return_move_and_place_s": return_move_and_place_s,
        "return_conflict_s": return_conflict_s,
        "read_gib": read_bytes / (1024**3),
    }


def move_time_s(geometry: dict, movement: dict, src_level: int, src_slot: int, dst_level: int, dst_slot: int) -> float:
    vertical_s = abs(dst_level - src_level) * movement["vertical_s_per_level"]
    slot_width_m = geometry["rack_length_m"] / (geometry["slots_per_rack"] - 1)
    horizontal_m = abs(dst_slot - src_slot) * slot_width_m
    return vertical_s + horizontal_time_s(horizontal_m, movement)


def horizontal_time_s(distance_m: float, movement: dict) -> float:
    if distance_m <= 0:
        return 0.0
    vmax = movement["horizontal_max_m_s"]
    accel = movement["horizontal_accel_m_s2"]
    accel_distance = vmax * vmax / accel
    if distance_m <= accel_distance:
        travel_s = 2.0 * math.sqrt(distance_m / accel)
    else:
        travel_s = 2.0 * (vmax / accel) + (distance_m - accel_distance) / vmax
    return max(movement["horizontal_min_s"], travel_s)


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


def plot_reader_breakdown(rows: list[dict[str, float]], figures_dir: Path) -> None:
    labels = [int(row["shuttle_count"]) for row in rows]
    load = [row["reader_load_s"] / 60 for row in rows]
    read = [row["reader_read_s"] / 60 for row in rows]
    unload = [row["reader_unload_s"] / 60 for row in rows]
    wait = [row["reader_wait_s"] / 60 for row in rows]

    fig, ax = plt.subplots(figsize=(7.0, 3.9))
    bottom = [0.0] * len(rows)
    for values, label, color in [
        (load, "Reader load", BLUE),
        (read, "Reader read", GREEN),
        (unload, "Reader unload", ORANGE),
        (wait, "Reader waits for glass", RED),
    ]:
        ax.bar(labels, values, bottom=bottom, label=label, color=color)
        bottom = [current + value for current, value in zip(bottom, values, strict=False)]
    ax.set_xlabel("Number of shuttles")
    ax.set_ylabel("Accumulated time (minutes)")
    ax.set_title("Reader-side time breakdown, feeder mode")
    ax.set_xticks(labels)
    ax.legend(frameon=False, fontsize=8)
    apply_style(ax)
    save(fig, figures_dir, "feeder_reader_time_breakdown")


def plot_fetch_breakdown(rows: list[dict[str, float]], figures_dir: Path) -> None:
    labels = [int(row["shuttle_count"]) for row in rows]
    move = [(row["fetch_move_to_glass_s"] + row["fetch_move_to_buffer_s"]) / 60 for row in rows]
    pick = [row["fetch_pick_s"] / 60 for row in rows]
    place = [row["fetch_place_buffer_s"] / 60 for row in rows]
    buffer_wait = [row["feeder_slot_wait_s"] / 60 for row in rows]
    conflict = [row["fetch_conflict_s"] / 60 for row in rows]

    fig, ax = plt.subplots(figsize=(7.0, 3.9))
    bottom = [0.0] * len(rows)
    for values, label, color in [
        (move, "Move to/from rack", BLUE),
        (pick, "Pick", GREEN),
        (place, "Place into feeder", ORANGE),
        (buffer_wait, "Wait for feeder slot", GRAY),
        (conflict, "Conflict penalty", RED),
    ]:
        ax.bar(labels, values, bottom=bottom, label=label, color=color)
        bottom = [current + value for current, value in zip(bottom, values, strict=False)]
    ax.set_xlabel("Number of shuttles")
    ax.set_ylabel("Accumulated shuttle-side time (minutes)")
    ax.set_title("Fetch-side work breakdown, feeder mode")
    ax.set_xticks(labels)
    ax.legend(frameon=False, fontsize=8, ncol=2)
    apply_style(ax)
    save(fig, figures_dir, "feeder_fetch_time_breakdown")


def write_markdown(rows: list[dict[str, float]], path: Path, batch_size: int) -> None:
    best = max(rows, key=lambda row: row["throughput_req_per_s"])
    service_ops = int(best["service_ops"])
    load_unload_min = (best["reader_load_s"] + best["reader_unload_s"]) / 60.0
    lines = [
        "# Feeder Buffer Time Breakdown",
        "",
        f"Scope: feeder-buffer experiment, `batch={batch_size}`, synthetic placement, 64GiB glass, request merge enabled.",
        "",
        "## Reader-Side Bottleneck",
        "",
        "| Shuttles | Throughput req/s | Completion min | Reader load min | Read min | Reader unload min | Reader wait min | Pipeline util |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| "
            f"{int(row['shuttle_count'])} | "
            f"{row['throughput_req_per_s']:.4f} | "
            f"{row['drive_makespan_s'] / 60:.2f} | "
            f"{row['reader_load_s'] / 60:.2f} | "
            f"{row['reader_read_s'] / 60:.2f} | "
            f"{row['reader_unload_s'] / 60:.2f} | "
            f"{row['reader_wait_s'] / 60:.2f} | "
            f"{row['reader_pipeline_utilization']:.1%} |"
        )

    lines.extend(
        [
            "",
            "## Fetch-Side Work",
            "",
            "| Shuttles | Move total min | Pick min | Feeder place min | Wait for buffer slot min | Fetch conflict min | Return/drain work min |",
            "|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in rows:
        move_total_s = row["fetch_move_to_glass_s"] + row["fetch_move_to_buffer_s"]
        lines.append(
            "| "
            f"{int(row['shuttle_count'])} | "
            f"{move_total_s / 60:.2f} | "
            f"{row['fetch_pick_s'] / 60:.2f} | "
            f"{row['fetch_place_buffer_s'] / 60:.2f} | "
            f"{row['feeder_slot_wait_s'] / 60:.2f} | "
            f"{row['fetch_conflict_s'] / 60:.2f} | "
            f"{row['return_total_s'] / 60:.2f} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            f"The best observed point among these samples is `{int(best['shuttle_count'])}` shuttles at `{best['throughput_req_per_s']:.4f}` requests/s.",
            "",
            "At 1-2 shuttles the reader still waits for glass, so the system is shuttle/fetch limited.",
            "",
            "At 4 shuttles and beyond, reader waiting for glass is almost zero and reader pipeline utilization is about 100%. "
            "The bottleneck moves to the single reader pipeline.",
            "",
            f"Inside the reader pipeline, load and unload dominate. For batch {batch_size} there are {service_ops} merged glass service operations, "
            f"so 3s load + 3s unload costs {load_unload_min:.1f} minutes total before counting actual read time.",
            "",
            "The actual read time is much smaller than load/unload time under this trace and request-size model, so faster shuttles or more shuttles cannot help after the feeder is kept full.",
            "",
            "Return/drain work is still substantial, but with the current fetch-priority feeder model it does not determine drive throughput; it mainly extends system drain time.",
            "",
            "## Figures",
            "",
            "- `figures/feeder_reader_time_breakdown.pdf`",
            "- `figures/feeder_fetch_time_breakdown.pdf`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
