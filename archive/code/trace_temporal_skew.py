from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
import csv
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import mean
from typing import Any

from .panel_static_zone import (
    PanelGeometryConfig,
    PanelMovementConfig,
    PanelRequest,
    PanelRequestDetail,
    PanelStaticZoneConfig,
    PanelStaticZoneResult,
    PanelStaticZoneSimulator,
    PanelTimingConfig,
    PanelWorkloadConfig,
    merge_panel_requests,
)
from .trace import TraceRequest, iter_trace


@dataclass(frozen=True)
class TemporalWorkloadConfig:
    name: str
    display_name: str
    target_hot_task_fraction: float | None

    def validate(self) -> None:
        if not self.name:
            raise ValueError("temporal workload name cannot be empty")
        if self.target_hot_task_fraction is not None and not 0.0 <= self.target_hot_task_fraction <= 1.0:
            raise ValueError("target_hot_task_fraction must be between 0 and 1")


@dataclass(frozen=True)
class TracePlacementConfig:
    stripe_bytes: int
    platter_count: int
    hash_seed: int

    def validate(self) -> None:
        if self.stripe_bytes <= 0:
            raise ValueError("placement.stripe_bytes must be positive")
        if self.platter_count <= 0:
            raise ValueError("placement.platter_count must be positive")


@dataclass(frozen=True)
class TraceTemporalSkewConfig:
    output_dir: Path
    trace_path: Path
    max_read_requests: int
    source_merge_window_requests: int
    execution_epoch_tasks: int
    order_seed: int
    workloads: tuple[TemporalWorkloadConfig, ...]
    placement: TracePlacementConfig
    geometry: PanelGeometryConfig
    movement: PanelMovementConfig
    timing: PanelTimingConfig

    def validate(self) -> None:
        self.geometry.validate()
        self.movement.validate()
        self.timing.validate()
        self.placement.validate()
        if self.max_read_requests <= 0:
            raise ValueError("max_read_requests must be positive")
        if self.source_merge_window_requests <= 0:
            raise ValueError("source_merge_window_requests must be positive")
        if self.execution_epoch_tasks <= 0:
            raise ValueError("execution_epoch_tasks must be positive")
        if not self.workloads:
            raise ValueError("workloads cannot be empty")
        for workload in self.workloads:
            workload.validate()
        zone_count = self.geometry.levels // self.geometry.zone_height_racks * 2
        physical_positions = zone_count * self.geometry.zone_height_racks * self.geometry.slots_per_half
        if self.placement.platter_count != physical_positions:
            raise ValueError("placement.platter_count must equal the number of physical panel positions")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "output_dir": str(self.output_dir),
            "trace_path": str(self.trace_path),
            "max_read_requests": self.max_read_requests,
            "source_merge_window_requests": self.source_merge_window_requests,
            "execution_epoch_tasks": self.execution_epoch_tasks,
            "order_seed": self.order_seed,
            "workloads": [asdict(workload) for workload in self.workloads],
            "placement": asdict(self.placement),
            "geometry": asdict(self.geometry),
            "movement": asdict(self.movement),
            "timing": asdict(self.timing),
        }


@dataclass(frozen=True)
class TemporalStudyRun:
    workload: TemporalWorkloadConfig
    result: PanelStaticZoneResult
    epochs: list[list[PanelRequest]]
    epoch_rows: list[dict[str, Any]]
    summary_row: dict[str, Any]


@dataclass(frozen=True)
class TraceTemporalSkewResult:
    source_stats: dict[str, Any]
    runs: list[TemporalStudyRun]
    zone_rows: list[dict[str, Any]]


def load_trace_temporal_skew_config(path: str | Path) -> TraceTemporalSkewConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    base_dir = config_path.parent.parent if config_path.parent.name == "configs" else Path.cwd()
    output_dir = _resolve_path(raw["output_dir"], base_dir)
    trace_path = _resolve_path(raw["trace_path"], base_dir)
    config = TraceTemporalSkewConfig(
        output_dir=output_dir,
        trace_path=trace_path,
        max_read_requests=int(raw["max_read_requests"]),
        source_merge_window_requests=int(raw["source_merge_window_requests"]),
        execution_epoch_tasks=int(raw["execution_epoch_tasks"]),
        order_seed=int(raw.get("order_seed", 0)),
        workloads=tuple(TemporalWorkloadConfig(**workload) for workload in raw["workloads"]),
        placement=TracePlacementConfig(**raw["placement"]),
        geometry=PanelGeometryConfig(**raw["geometry"]),
        movement=PanelMovementConfig(**raw["movement"]),
        timing=PanelTimingConfig(**raw["timing"]),
    )
    config.validate()
    return config


def run_trace_temporal_skew_study(config: TraceTemporalSkewConfig) -> TraceTemporalSkewResult:
    trace_requests = _load_read_requests(config)
    template = PanelStaticZoneSimulator(_panel_config(config, "source"))
    atomic_tasks = build_atomic_trace_tasks(config, template, trace_requests)
    source_signature = task_multiset_signature(atomic_tasks)
    source_stats = {
        "trace_rows": len(trace_requests),
        "trace_bytes": sum(request.size_bytes for request in trace_requests),
        "atomic_glass_tasks": len(atomic_tasks),
        "atomic_logical_requests": sum(task.merged_request_count for task in atomic_tasks),
        "atomic_bytes": sum(task.size_bytes for task in atomic_tasks),
        "task_multiset_sha256": source_signature,
        "source_merge_windows": math.ceil(len(trace_requests) / config.source_merge_window_requests),
    }

    runs: list[TemporalStudyRun] = []
    zone_rows: list[dict[str, Any]] = []
    for workload in config.workloads:
        ordered = reorder_tasks_for_workload(
            atomic_tasks,
            workload,
            template.zone_count,
            config.execution_epoch_tasks,
            config.order_seed,
        )
        if task_multiset_signature(ordered) != source_signature:
            raise RuntimeError(f"{workload.name} changed the atomic task multiset")
        epochs = _chunked(ordered, config.execution_epoch_tasks)
        simulator = PanelStaticZoneSimulator(_panel_config(config, workload.name))
        result, epoch_details = simulator.run_barrier_epochs(epochs)
        epoch_rows = _build_epoch_rows(workload, epochs, epoch_details, simulator.zone_count)
        summary_row = _build_summary_row(workload, result, epoch_rows, source_signature)
        runs.append(
            TemporalStudyRun(
                workload=workload,
                result=result,
                epochs=epochs,
                epoch_rows=epoch_rows,
                summary_row=summary_row,
            )
        )
        zone_rows.extend(
            {
                "workload": workload.name,
                "display_name": workload.display_name,
                **row,
            }
            for row in result.zone_rows
        )
    return TraceTemporalSkewResult(source_stats=source_stats, runs=runs, zone_rows=zone_rows)


def build_atomic_trace_tasks(
    config: TraceTemporalSkewConfig,
    simulator: PanelStaticZoneSimulator,
    trace_requests: list[TraceRequest],
) -> list[PanelRequest]:
    atomic_tasks: list[PanelRequest] = []
    for source_window in _chunked(trace_requests, config.source_merge_window_requests):
        panel_requests = [
            _panel_request_for_trace(config, simulator, request)
            for request in source_window
        ]
        atomic_tasks.extend(merge_panel_requests(panel_requests))
    return sorted(atomic_tasks, key=lambda request: request.request_index)


def reorder_tasks_for_workload(
    tasks: list[PanelRequest],
    workload: TemporalWorkloadConfig,
    zone_count: int,
    epoch_tasks: int,
    seed: int,
) -> list[PanelRequest]:
    if workload.target_hot_task_fraction is None:
        return list(tasks)

    queues = [deque(task for task in tasks if task.zone_id == zone_id) for zone_id in range(zone_count)]
    ordered: list[PanelRequest] = []
    phase = 0
    remaining = len(tasks)
    rotation_offset = seed % zone_count
    while remaining > 0:
        phase_size = min(epoch_tasks, remaining)
        target_hot = round(phase_size * workload.target_hot_task_fraction)
        preferred = (phase + rotation_offset) % zone_count
        candidates = sorted(
            range(zone_count),
            key=lambda zone: (
                len(queues[zone]) < target_hot,
                -len(queues[zone]),
                (zone - preferred) % zone_count,
            ),
        )
        hot_zone = candidates[0]
        epoch: list[PanelRequest] = []
        hot_take = min(target_hot, len(queues[hot_zone]))
        epoch.extend(queues[hot_zone].popleft() for _ in range(hot_take))

        background_cursor = (hot_zone + 1) % zone_count
        while len(epoch) < phase_size:
            available = [zone for zone in range(zone_count) if queues[zone]]
            if not available:
                break
            non_hot = [zone for zone in available if zone != hot_zone]
            pool = non_hot or available
            chosen = min(pool, key=lambda zone: ((zone - background_cursor) % zone_count, -len(queues[zone])))
            epoch.append(queues[chosen].popleft())
            background_cursor = (chosen + 1) % zone_count

        ordered.extend(epoch)
        remaining -= len(epoch)
        phase += 1
    return ordered


def task_multiset_signature(tasks: list[PanelRequest]) -> str:
    digest = hashlib.sha256()
    identities = sorted(
        (
            task.request_index,
            task.platter_id,
            task.size_bytes,
            task.merged_request_count,
        )
        for task in tasks
    )
    for identity in identities:
        digest.update((":".join(str(value) for value in identity) + "\n").encode("ascii"))
    return digest.hexdigest()


def write_trace_temporal_skew_outputs(
    config: TraceTemporalSkewConfig,
    study: TraceTemporalSkewResult,
) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    _write_rows(config.output_dir / "summary.csv", [run.summary_row for run in study.runs])
    _write_rows(
        config.output_dir / "epoch_detail.csv",
        [row for run in study.runs for row in run.epoch_rows],
    )
    _write_rows(config.output_dir / "zone_summary.csv", study.zone_rows)
    (config.output_dir / "config.json").write_text(
        json.dumps(config.to_json_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    (config.output_dir / "source_summary.json").write_text(
        json.dumps(study.source_stats, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_analysis(config.output_dir / "TRACE_TEMPORAL_SKEW_ANALYSIS.md", config, study)
    figures_dir = config.output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    write_trace_temporal_skew_figures(study, figures_dir)


def write_trace_temporal_skew_figures(study: TraceTemporalSkewResult, output_dir: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(Path("outputs/.mplconfig").resolve()))
    os.environ.setdefault("XDG_CACHE_HOME", str(Path("outputs/.cache").resolve()))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.size": 9,
            "axes.titlesize": 11,
            "axes.labelsize": 9,
            "legend.fontsize": 8,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )
    rows = [run.summary_row for run in study.runs]
    labels = [row["display_name"] for row in rows]
    colors = ["#2F6B9A", "#D9822B", "#C84C4C"]

    fig, axes = plt.subplots(1, 3, figsize=(11.0, 3.6))
    axes[0].bar(labels, [row["makespan_h"] for row in rows], color=colors)
    axes[1].bar(labels, [row["throughput_req_per_s"] for row in rows], color=colors)
    axes[2].bar(labels, [row["latency_p99_h"] for row in rows], color=colors)
    axes[0].set_ylabel("Makespan (h)")
    axes[1].set_ylabel("Logical throughput (req/s)")
    axes[2].set_ylabel("P99 epoch latency (h)")
    for ax, title in zip(axes, ["A. Batch completion", "B. Throughput", "C. Tail latency"]):
        ax.set_title(title)
        ax.tick_params(axis="x", rotation=18)
        _style(ax)
    _save(fig, output_dir, "fig1_performance_comparison")

    fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.8))
    width = 0.24
    x = list(range(len(rows)))
    for offset, field, label, color in [
        (-width, "epoch_max_zone_work_share_mean", "Mean", "#2F6B9A"),
        (0.0, "epoch_max_zone_work_share_p95", "P95", "#D9822B"),
        (width, "epoch_max_zone_work_share_max", "Maximum", "#C84C4C"),
    ]:
        axes[0].bar([value + offset for value in x], [row[field] * 100 for row in rows], width, label=label, color=color)
    axes[0].axhline(12.5, color="#667085", linestyle=":", linewidth=1.2, label="Perfect balance")
    axes[0].set_xticks(x, labels)
    axes[0].set_ylabel("Largest zone's active-work share (%)")
    axes[0].set_title("A. Temporal zone skew")
    axes[0].legend(frameon=False, ncol=2)
    productive = [row["capacity_efficiency"] * 100 for row in rows]
    stranded = [100 - value for value in productive]
    axes[1].bar(labels, productive, color=colors, label="Productive")
    axes[1].bar(labels, stranded, bottom=productive, color="#D7DEE8", label="Stranded")
    for index, value in enumerate(productive):
        axes[1].text(index, value / 2, f"{value:.1f}%", ha="center", va="center", color="white")
        axes[1].text(
            index,
            value + stranded[index] / 2,
            f"{stranded[index]:.1f}%\nstranded",
            ha="center",
            va="center",
            color="#344054",
        )
    axes[1].set_ylim(0, 103)
    axes[1].set_ylabel("Available zone-time capacity (%)")
    axes[1].set_title("B. Capacity lost at epoch barriers")
    for ax in axes:
        ax.tick_params(axis="x", rotation=18)
        _style(ax)
    _save(fig, output_dir, "fig2_zone_skew_and_stranding")

    fig, ax = plt.subplots(figsize=(9.4, 4.0))
    for run, color in zip(study.runs, colors):
        ax.plot(
            [row["epoch_index"] for row in run.epoch_rows],
            [row["max_zone_work_share"] * 100 for row in run.epoch_rows],
            color=color,
            linewidth=1.5,
            label=run.workload.display_name,
        )
    ax.axhline(12.5, color="#667085", linestyle=":", linewidth=1.2, label="Perfect balance")
    last_epoch = max(row["epoch_index"] for run in study.runs for row in run.epoch_rows)
    ax.axvspan(last_epoch - 1.5, last_epoch + 0.5, color="#EAECF0", alpha=0.55, zorder=0)
    ax.text(last_epoch - 0.5, 33, "Residual\ndrain", ha="center", va="center", color="#667085")
    ax.set_xlabel("Execution epoch")
    ax.set_ylabel("Largest zone's active-work share (%)")
    ax.set_title("Short-lived regional hotspots across trace-derived epochs")
    ax.legend(frameon=False, ncol=1, loc="upper left", bbox_to_anchor=(1.01, 1.0))
    _style(ax)
    _save(fig, output_dir, "fig3_temporal_skew_over_time")

    fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.8))
    zone_ids = [int(row["zone_id"]) for row in study.runs[0].result.zone_rows]
    for run, color in zip(study.runs, colors):
        total_logical = run.result.summary["request_count"]
        axes[0].plot(
            zone_ids,
            [row["logical_request_count"] / total_logical * 100 for row in run.result.zone_rows],
            color=color,
            marker="o",
            linewidth=1.5,
            label=run.workload.display_name,
        )
    axes[0].set_xlabel("Static zone")
    axes[0].set_ylabel("Whole-trace logical request share (%)")
    axes[0].set_title("A. Global zone totals are unchanged")
    axes[0].text(
        0.02,
        0.04,
        "All three curves overlap exactly",
        transform=axes[0].transAxes,
        color="#667085",
    )
    axes[0].legend(frameon=False)
    movement = [row["movement_share"] * 100 for row in rows]
    fixed = [row["fixed_share"] * 100 for row in rows]
    reader = [row["reader_share"] * 100 for row in rows]
    axes[1].bar(labels, movement, color="#2F6B9A", label="Movement")
    axes[1].bar(labels, fixed, bottom=movement, color="#4C9F70", label="Fixed mechanics")
    axes[1].bar(labels, reader, bottom=[a + b for a, b in zip(movement, fixed)], color="#7A5EA8", label="Reader")
    axes[1].set_ylim(0, 103)
    axes[1].set_ylabel("Active-cycle time share (%)")
    axes[1].set_title("B. Per-task hardware cost stays fixed")
    axes[1].legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.18))
    for ax in axes:
        ax.tick_params(axis="x", rotation=18)
        _style(ax)
    _save(fig, output_dir, "fig4_controls_and_bottleneck")

    fig, axes = plt.subplots(2, 2, figsize=(9.6, 7.1))
    axes[0, 0].bar(labels, [row["epoch_max_zone_work_share_p95"] * 100 for row in rows], color=colors)
    axes[0, 1].bar(labels, [row["capacity_efficiency"] * 100 for row in rows], color=colors)
    axes[1, 0].bar(labels, [row["makespan_h"] for row in rows], color=colors)
    axes[1, 1].bar(labels, [row["latency_p99_h"] for row in rows], color=colors)
    axes[0, 0].set_ylabel("P95 largest-zone work share (%)")
    axes[0, 1].set_ylabel("Capacity efficiency (%)")
    axes[1, 0].set_ylabel("Makespan (h)")
    axes[1, 1].set_ylabel("P99 latency (h)")
    titles = [
        "A. Order creates regional bursts",
        "B. Static ownership strands capacity",
        "C. Barriers extend completion",
        "D. Hot-zone queues dominate tails",
    ]
    for ax, title in zip(axes.flat, titles):
        ax.set_title(title)
        ax.tick_params(axis="x", rotation=18)
        _style(ax)
    fig.suptitle("Same trace tasks, different temporal ordering under strict static zones", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    _save(fig, output_dir, "fig5_trace_order_research_story", tight=False)


def _load_read_requests(config: TraceTemporalSkewConfig) -> list[TraceRequest]:
    requests: list[TraceRequest] = []
    for request in iter_trace(config.trace_path):
        if request.io_type != "R":
            continue
        requests.append(request)
        if len(requests) >= config.max_read_requests:
            break
    if len(requests) < config.max_read_requests:
        raise ValueError(
            f"trace contains only {len(requests)} read requests, expected {config.max_read_requests}"
        )
    return requests


def _panel_config(
    config: TraceTemporalSkewConfig,
    workload_name: str,
) -> PanelStaticZoneConfig:
    return PanelStaticZoneConfig(
        output_dir=config.output_dir / "runs" / workload_name,
        seed=config.order_seed,
        geometry=config.geometry,
        movement=config.movement,
        timing=config.timing,
        workload=PanelWorkloadConfig(
            batch_size=config.max_read_requests,
            request_size_bytes=1,
            placement="uniform_round_robin",
            request_merge=True,
        ),
    )


def _panel_request_for_trace(
    config: TraceTemporalSkewConfig,
    simulator: PanelStaticZoneSimulator,
    request: TraceRequest,
) -> PanelRequest:
    stripe_id = request.offset // config.placement.stripe_bytes
    platter_id = _hash_u64(stripe_id ^ config.placement.hash_seed) % config.placement.platter_count
    zone_capacity = config.geometry.zone_height_racks * config.geometry.slots_per_half
    zone_id, local_platter = divmod(platter_id, zone_capacity)
    local_level, slot = divmod(local_platter, config.geometry.slots_per_half)
    return simulator.make_request(
        request_index=request.index,
        zone_id=zone_id,
        local_level=local_level,
        slot_in_half=slot,
        size_bytes=request.size_bytes,
    )


def _build_epoch_rows(
    workload: TemporalWorkloadConfig,
    epochs: list[list[PanelRequest]],
    detail_epochs: list[list[PanelRequestDetail]],
    zone_count: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for epoch_index, (requests, details) in enumerate(zip(epochs, detail_epochs)):
        logical_by_zone = [0] * zone_count
        tasks_by_zone = [0] * zone_count
        work_by_zone = [0.0] * zone_count
        for request in requests:
            logical_by_zone[request.zone_id] += request.merged_request_count
            tasks_by_zone[request.zone_id] += 1
        for detail in details:
            work_by_zone[detail.zone_id] += detail.cycle_s
        logical_total = sum(logical_by_zone)
        task_total = sum(tasks_by_zone)
        active_work_s = sum(work_by_zone)
        epoch_start_s = min((detail.arrival_s for detail in details), default=0.0)
        epoch_end_s = max((detail.return_done_s for detail in details), default=epoch_start_s)
        duration_s = epoch_end_s - epoch_start_s
        max_work = max(work_by_zone, default=0.0)
        rows.append(
            {
                "workload": workload.name,
                "display_name": workload.display_name,
                "epoch_index": epoch_index,
                "epoch_start_s": epoch_start_s,
                "epoch_duration_s": duration_s,
                "task_count": task_total,
                "logical_request_count": logical_total,
                "critical_zone": work_by_zone.index(max_work) if work_by_zone else -1,
                "max_zone_task_share": max(tasks_by_zone, default=0) / task_total if task_total else 0.0,
                "max_zone_logical_share": max(logical_by_zone, default=0) / logical_total if logical_total else 0.0,
                "max_zone_work_share": max_work / active_work_s if active_work_s > 0 else 0.0,
                "work_max_mean_ratio": max_work / mean(work_by_zone) if mean(work_by_zone) > 0 else 0.0,
                "work_jain_fairness": _jain_fairness(work_by_zone),
                "capacity_efficiency": active_work_s / (zone_count * duration_s) if duration_s > 0 else 0.0,
                "stranded_capacity_share": 1.0 - active_work_s / (zone_count * duration_s)
                if duration_s > 0
                else 0.0,
            }
        )
    return rows


def _build_summary_row(
    workload: TemporalWorkloadConfig,
    result: PanelStaticZoneResult,
    epoch_rows: list[dict[str, Any]],
    source_signature: str,
) -> dict[str, Any]:
    summary = result.summary
    weighted_latencies = [
        detail.latency_s
        for detail in result.details
        for _ in range(detail.merged_request_count)
    ]
    weighted_latencies.sort()
    max_work_shares = sorted(float(row["max_zone_work_share"]) for row in epoch_rows)
    target = workload.target_hot_task_fraction or 0.0
    return {
        "workload": workload.name,
        "display_name": workload.display_name,
        "target_hot_task_fraction": target,
        "task_multiset_sha256": source_signature,
        "epoch_count": len(epoch_rows),
        "logical_request_count": summary["request_count"],
        "physical_task_count": summary["service_operation_count"],
        "total_mib": summary["throughput_mib_per_s"] * summary["drive_makespan_s"],
        "makespan_s": summary["drive_makespan_s"],
        "makespan_h": summary["drive_makespan_s"] / 3600,
        "throughput_req_per_s": summary["throughput_req_per_s"],
        "throughput_mib_per_s": summary["throughput_mib_per_s"],
        "latency_p50_h": _percentile(weighted_latencies, 0.50) / 3600,
        "latency_p95_h": _percentile(weighted_latencies, 0.95) / 3600,
        "latency_p99_h": _percentile(weighted_latencies, 0.99) / 3600,
        "capacity_efficiency": summary["static_capacity_efficiency"],
        "stranded_capacity_share": summary["stranded_capacity_share"],
        "ownership_slowdown_vs_ideal": summary["ownership_slowdown_vs_ideal"],
        "epoch_max_zone_work_share_mean": mean(max_work_shares),
        "epoch_max_zone_work_share_p95": _percentile(max_work_shares, 0.95),
        "epoch_max_zone_work_share_max": max(max_work_shares, default=0.0),
        "epoch_work_max_mean_ratio_mean": mean(float(row["work_max_mean_ratio"]) for row in epoch_rows),
        "epoch_work_jain_fairness_mean": mean(float(row["work_jain_fairness"]) for row in epoch_rows),
        "epoch_duration_s_mean": mean(float(row["epoch_duration_s"]) for row in epoch_rows),
        "movement_share": summary["aggregate_component_active_shares"]["shuttle_movement_s"],
        "fixed_share": summary["aggregate_component_active_shares"]["fixed_mechanical_s"],
        "reader_share": summary["aggregate_component_active_shares"]["reader_data_transfer_s"],
    }


def _write_analysis(
    path: Path,
    config: TraceTemporalSkewConfig,
    study: TraceTemporalSkewResult,
) -> None:
    rows = [run.summary_row for run in study.runs]
    normal, moderate, severe = rows
    table = [
        "| Workload | P95 largest-zone work share | Imbalance vs 12.5% balance | Mean Jain fairness | Capacity efficiency | Makespan | Throughput | P99 latency |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        table.append(
            f"| {row['display_name']} | {row['epoch_max_zone_work_share_p95'] * 100:.1f}% | "
            f"{row['epoch_max_zone_work_share_p95'] / 0.125:.2f}x | "
            f"{row['epoch_work_jain_fairness_mean']:.3f} | {row['capacity_efficiency'] * 100:.1f}% | "
            f"{row['makespan_h']:.2f} h | {row['throughput_req_per_s']:.3f} req/s | "
            f"{row['latency_p99_h']:.2f} h |"
        )
    lines = [
        "# Trace-Derived Temporal Skew under Strict Static Zones",
        "",
        "## Experiment contract",
        "",
        f"- Source trace: `{config.trace_path}`.",
        f"- Read requests: {study.source_stats['trace_rows']:,} in original timestamp order.",
        f"- Stable mapping: {config.placement.stripe_bytes / 1024**2:.0f} MiB logical stripes are hashed onto {config.placement.platter_count:,} physical glass positions.",
        f"- Merge: performed only inside each original {config.source_merge_window_requests:,}-request source window before any reordering.",
        f"- Atomic tasks after merge: {study.source_stats['atomic_glass_tasks']:,}; every workload has the same SHA-256 task multiset signature.",
        f"- Execution: {config.execution_epoch_tasks} atomic tasks per barrier-synchronized epoch.",
        "- Reordering preserves every zone's internal task order; only cross-zone interleaving changes.",
        "",
        "## Workload definitions",
        "",
        "1. `Normal`: original trace order after source-window merge.",
        "2. `Moderate skew`: each epoch attempts to draw 50% of atomic tasks from one rotating hot zone.",
        "3. `Severe skew`: each epoch attempts to draw 80% of atomic tasks from one rotating hot zone.",
        "",
        "The hotspot rotates and is temporary. Whole-trace per-zone totals, task bytes, merge output, and each zone's internal service order are unchanged.",
        "The final one or two epochs are residual drain epochs: too few tasks remain in any one zone to sustain the target hot share. P95 skew is used as the primary intensity metric so this finite-trace tail does not redefine the workload.",
        "",
        "## Results",
        "",
        *table,
        "",
        f"Moderate temporal skew changes makespan by {moderate['makespan_h'] / normal['makespan_h']:.2f}x and severe skew by {severe['makespan_h'] / normal['makespan_h']:.2f}x relative to normal order.",
        f"Capacity efficiency falls from {normal['capacity_efficiency'] * 100:.1f}% to {moderate['capacity_efficiency'] * 100:.1f}% and {severe['capacity_efficiency'] * 100:.1f}% even though the global task multiset is identical.",
        "",
        "## Why order matters under the epoch model",
        "",
        "Strict static execution cannot move a hot epoch's work to cold owners. Cold zones finish early and wait at the epoch barrier, so temporary imbalance becomes stranded zone-time. The next epoch may move the hotspot elsewhere, but it cannot recover capacity already lost in the previous epoch.",
        "",
        "This isolates a temporal version of the static-ownership problem: the whole trace can be globally balanced while each short control window is strongly imbalanced.",
        "",
        "## Evidence boundary",
        "",
        "The epoch barrier represents a batch/phase completion dependency. Without a barrier or deadline, backlog from different phases can overlap and partially smooth temporal skew, so order may affect tail latency more than final throughput. A later online experiment should sweep epoch size and arrival rate, then compare strict static, work stealing, and adaptive ownership with the same ordered task stream.",
        "",
        "## Figure guide",
        "",
        "- `fig1_performance_comparison`: makespan, throughput, and P99 latency.",
        "- `fig2_zone_skew_and_stranding`: temporal skew magnitude and lost capacity.",
        "- `fig3_temporal_skew_over_time`: short-lived hotspot intensity per epoch.",
        "- `fig4_controls_and_bottleneck`: unchanged global zone totals and hardware cost mix.",
        "- `fig5_trace_order_research_story`: condensed paper-ready evidence chain.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _hash_u64(value: int) -> int:
    value &= 0xFFFFFFFFFFFFFFFF
    value ^= value >> 30
    value = (value * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    value ^= value >> 27
    value = (value * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    value ^= value >> 31
    return value


def _jain_fairness(values: list[float]) -> float:
    total = sum(values)
    square_sum = sum(value * value for value in values)
    return total * total / (len(values) * square_sum) if square_sum > 0 else 1.0


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    position = (len(values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    fraction = position - lower
    return values[lower] * (1.0 - fraction) + values[upper] * fraction


def _chunked(values, size: int):
    return [values[index : index + size] for index in range(0, len(values), size)]


def _resolve_path(value: str, base_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _style(ax) -> None:
    ax.set_axisbelow(True)
    ax.grid(True, axis="y", color="#D7DEE8", linewidth=0.7, zorder=0)
    ax.grid(False, axis="x")
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color("#9AA5B1")
    ax.spines["bottom"].set_color("#9AA5B1")
    ax.tick_params(colors="#1F2933")


def _save(fig, output_dir: Path, name: str, tight: bool = True) -> None:
    if tight:
        fig.tight_layout()
    fig.savefig(output_dir / f"{name}.pdf", bbox_inches="tight", facecolor="white", transparent=False)
    fig.savefig(
        output_dir / f"{name}.png",
        dpi=300,
        bbox_inches="tight",
        facecolor="white",
        transparent=False,
    )
    import matplotlib.pyplot as plt

    plt.close(fig)
