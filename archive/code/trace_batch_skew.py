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
class BatchWorkloadConfig:
    name: str
    display_name: str
    target_hot_request_fraction: float | None

    def validate(self) -> None:
        if not self.name:
            raise ValueError("batch workload name cannot be empty")
        if self.target_hot_request_fraction is not None and not 0.0 <= self.target_hot_request_fraction <= 1.0:
            raise ValueError("target_hot_request_fraction must be between 0 and 1")


@dataclass(frozen=True)
class BatchPlacementConfig:
    stripe_bytes: int
    platter_count: int
    hash_seed: int

    def validate(self) -> None:
        if self.stripe_bytes <= 0:
            raise ValueError("placement.stripe_bytes must be positive")
        if self.platter_count <= 0:
            raise ValueError("placement.platter_count must be positive")


@dataclass(frozen=True)
class TraceBatchSkewConfig:
    output_dir: Path
    trace_path: Path
    max_read_requests: int
    batch_size: int
    order_seed: int
    workloads: tuple[BatchWorkloadConfig, ...]
    placement: BatchPlacementConfig
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
        if self.batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if self.max_read_requests % self.batch_size != 0:
            raise ValueError("max_read_requests must be divisible by batch_size")
        if not self.workloads:
            raise ValueError("workloads cannot be empty")
        for workload in self.workloads:
            workload.validate()
        zone_count = self.geometry.levels // self.geometry.zone_height_racks * 2
        physical_positions = zone_count * self.geometry.zone_height_racks * self.geometry.slots_per_half
        if self.placement.platter_count != physical_positions:
            raise ValueError("placement.platter_count must equal physical panel positions")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "output_dir": str(self.output_dir),
            "trace_path": str(self.trace_path),
            "max_read_requests": self.max_read_requests,
            "batch_size": self.batch_size,
            "order_seed": self.order_seed,
            "workloads": [asdict(workload) for workload in self.workloads],
            "placement": asdict(self.placement),
            "geometry": asdict(self.geometry),
            "movement": asdict(self.movement),
            "timing": asdict(self.timing),
        }


@dataclass(frozen=True)
class MappedTraceRequest:
    source_index: int
    size_bytes: int
    platter_id: int
    zone_id: int
    local_level: int
    slot_in_half: int


@dataclass(frozen=True)
class BatchStudyRun:
    workload: BatchWorkloadConfig
    logical_batches: list[list[MappedTraceRequest]]
    merged_batches: list[list[PanelRequest]]
    result: PanelStaticZoneResult
    batch_rows: list[dict[str, Any]]
    summary_row: dict[str, Any]


@dataclass(frozen=True)
class TraceBatchSkewResult:
    source_stats: dict[str, Any]
    runs: list[BatchStudyRun]
    zone_rows: list[dict[str, Any]]


def load_trace_batch_skew_config(path: str | Path) -> TraceBatchSkewConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    base_dir = config_path.parent.parent if config_path.parent.name == "configs" else Path.cwd()
    config = TraceBatchSkewConfig(
        output_dir=_resolve_path(raw["output_dir"], base_dir),
        trace_path=_resolve_path(raw["trace_path"], base_dir),
        max_read_requests=int(raw["max_read_requests"]),
        batch_size=int(raw["batch_size"]),
        order_seed=int(raw.get("order_seed", 0)),
        workloads=tuple(BatchWorkloadConfig(**workload) for workload in raw["workloads"]),
        placement=BatchPlacementConfig(**raw["placement"]),
        geometry=PanelGeometryConfig(**raw["geometry"]),
        movement=PanelMovementConfig(**raw["movement"]),
        timing=PanelTimingConfig(**raw["timing"]),
    )
    config.validate()
    return config


def run_trace_batch_skew_study(config: TraceBatchSkewConfig) -> TraceBatchSkewResult:
    trace_requests = _load_read_requests(config)
    mapped_requests = [_map_trace_request(config, request) for request in trace_requests]
    source_signature = logical_request_signature(mapped_requests)
    source_stats = {
        "trace_rows": len(mapped_requests),
        "trace_bytes": sum(request.size_bytes for request in mapped_requests),
        "batch_size": config.batch_size,
        "batch_count": len(mapped_requests) // config.batch_size,
        "logical_request_multiset_sha256": source_signature,
    }

    runs: list[BatchStudyRun] = []
    zone_rows: list[dict[str, Any]] = []
    zone_count = config.geometry.levels // config.geometry.zone_height_racks * 2
    for workload in config.workloads:
        ordered = reorder_logical_requests(
            mapped_requests,
            workload,
            zone_count,
            config.batch_size,
            config.order_seed,
        )
        if logical_request_signature(ordered) != source_signature:
            raise RuntimeError(f"{workload.name} changed the logical request multiset")
        logical_batches = _chunked(ordered, config.batch_size)
        simulator = PanelStaticZoneSimulator(_panel_config(config, workload.name))
        merged_batches = [
            merge_panel_requests(_make_panel_batch(simulator, batch, batch_index * config.batch_size))
            for batch_index, batch in enumerate(logical_batches)
        ]
        result, detail_batches = simulator.run_barrier_epochs(merged_batches)
        batch_rows = _build_batch_rows(workload, logical_batches, merged_batches, detail_batches, zone_count)
        summary_row = _build_summary_row(workload, result, batch_rows, source_signature)
        runs.append(
            BatchStudyRun(
                workload=workload,
                logical_batches=logical_batches,
                merged_batches=merged_batches,
                result=result,
                batch_rows=batch_rows,
                summary_row=summary_row,
            )
        )
        zone_rows.extend(
            {"workload": workload.name, "display_name": workload.display_name, **row}
            for row in result.zone_rows
        )
    return TraceBatchSkewResult(source_stats=source_stats, runs=runs, zone_rows=zone_rows)


def reorder_logical_requests(
    requests: list[MappedTraceRequest],
    workload: BatchWorkloadConfig,
    zone_count: int,
    batch_size: int,
    seed: int,
) -> list[MappedTraceRequest]:
    if workload.target_hot_request_fraction is None:
        return list(requests)
    queues = [deque(request for request in requests if request.zone_id == zone) for zone in range(zone_count)]
    ordered: list[MappedTraceRequest] = []
    batch_index = 0
    remaining = len(requests)
    rotation_offset = seed % zone_count
    while remaining > 0:
        current_size = min(batch_size, remaining)
        target_hot = round(current_size * workload.target_hot_request_fraction)
        preferred = (batch_index + rotation_offset) % zone_count
        candidates = sorted(
            range(zone_count),
            key=lambda zone: (
                len(queues[zone]) < target_hot,
                -len(queues[zone]),
                (zone - preferred) % zone_count,
            ),
        )
        hot_zone = candidates[0]
        batch: list[MappedTraceRequest] = []
        hot_take = min(target_hot, len(queues[hot_zone]))
        batch.extend(queues[hot_zone].popleft() for _ in range(hot_take))

        cursor = (hot_zone + 1) % zone_count
        while len(batch) < current_size:
            available = [zone for zone in range(zone_count) if queues[zone]]
            if not available:
                break
            non_hot = [zone for zone in available if zone != hot_zone]
            pool = non_hot or available
            chosen = min(pool, key=lambda zone: ((zone - cursor) % zone_count, -len(queues[zone])))
            batch.append(queues[chosen].popleft())
            cursor = (chosen + 1) % zone_count
        ordered.extend(batch)
        remaining -= len(batch)
        batch_index += 1
    return ordered


def logical_request_signature(requests: list[MappedTraceRequest]) -> str:
    digest = hashlib.sha256()
    for identity in sorted(
        (request.source_index, request.size_bytes, request.platter_id)
        for request in requests
    ):
        digest.update((":".join(str(value) for value in identity) + "\n").encode("ascii"))
    return digest.hexdigest()


def write_trace_batch_skew_outputs(config: TraceBatchSkewConfig, study: TraceBatchSkewResult) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    _write_rows(config.output_dir / "summary.csv", [run.summary_row for run in study.runs])
    _write_rows(config.output_dir / "batch_detail.csv", [row for run in study.runs for row in run.batch_rows])
    _write_rows(config.output_dir / "zone_summary.csv", study.zone_rows)
    (config.output_dir / "config.json").write_text(
        json.dumps(config.to_json_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    (config.output_dir / "source_summary.json").write_text(
        json.dumps(study.source_stats, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_analysis(config.output_dir / "TRACE_MULTI_BATCH_SKEW_ANALYSIS.md", config, study)
    figures_dir = config.output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    write_trace_batch_skew_figures(study, figures_dir)


def write_trace_batch_skew_figures(study: TraceBatchSkewResult, output_dir: Path) -> None:
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
    x = list(range(len(rows)))

    fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.7))
    width = 0.34
    axes[0].bar([value - width / 2 for value in x], [row["batch_max_zone_request_share_p95"] * 100 for row in rows], width, color="#2F6B9A", label="Logical requests")
    axes[0].bar([value + width / 2 for value in x], [row["batch_max_zone_work_share_p95"] * 100 for row in rows], width, color="#C84C4C", label="Post-merge active work")
    axes[0].axhline(12.5, color="#667085", linestyle=":", linewidth=1.2, label="Perfect balance")
    axes[0].set_xticks(x, labels)
    axes[0].set_ylabel("P95 busiest-zone share (%)")
    axes[0].set_title("A. How uneven is each batch?")
    axes[0].legend(frameon=False)
    productive = [row["capacity_efficiency"] * 100 for row in rows]
    stranded = [100 - value for value in productive]
    axes[1].bar(labels, productive, color=colors)
    axes[1].bar(labels, stranded, bottom=productive, color="#D7DEE8")
    for index, value in enumerate(productive):
        axes[1].text(index, value / 2, f"{value:.1f}%\nworking", ha="center", va="center", color="white")
        axes[1].text(index, value + stranded[index] / 2, f"{stranded[index]:.1f}%\nwaiting", ha="center", va="center", color="#344054")
    axes[1].set_ylim(0, 103)
    axes[1].set_ylabel("Total shuttle-reader capacity (%)")
    axes[1].set_title("B. How much capacity is useful?")
    for ax in axes:
        ax.tick_params(axis="x", rotation=18)
        _style(ax)
    _save(fig, output_dir, "fig1_batch_skew_and_capacity")

    fig, axes = plt.subplots(1, 3, figsize=(11.0, 3.6))
    axes[0].bar(labels, [row["makespan_h"] for row in rows], color=colors)
    axes[1].bar(labels, [row["throughput_req_per_s"] for row in rows], color=colors)
    axes[2].bar(labels, [row["latency_p99_h"] for row in rows], color=colors)
    axes[0].set_ylabel("Total completion time (h)")
    axes[1].set_ylabel("Logical throughput (req/s)")
    axes[2].set_ylabel("P99 request latency (h)")
    for ax, title in zip(axes, ["A. Finish time", "B. Throughput", "C. Slowest requests"]):
        ax.set_title(title)
        ax.tick_params(axis="x", rotation=18)
        _style(ax)
    _save(fig, output_dir, "fig2_performance_comparison")

    fig, axes = plt.subplots(1, 2, figsize=(9.8, 3.9))
    for run, color in zip(study.runs, colors):
        axes[0].plot(
            [row["batch_index"] for row in run.batch_rows],
            [row["max_zone_request_share"] * 100 for row in run.batch_rows],
            color=color,
            marker="o",
            linewidth=1.4,
            markersize=3,
            label=run.workload.display_name,
        )
        axes[1].plot(
            [row["batch_index"] for row in run.batch_rows],
            [row["max_zone_work_share"] * 100 for row in run.batch_rows],
            color=color,
            marker="o",
            linewidth=1.4,
            markersize=3,
            label=run.workload.display_name,
        )
    for ax in axes:
        ax.axhline(12.5, color="#667085", linestyle=":", linewidth=1.2)
        ax.axvspan(16.5, 19.5, color="#EAECF0", alpha=0.45, zorder=0)
        ax.set_xlabel("Batch index")
        _style(ax)
    axes[0].text(18.6, 75, "Residual\nbatches", ha="center", va="center", color="#667085")
    axes[0].set_ylabel("Busiest-zone logical request share (%)")
    axes[1].set_ylabel("Busiest-zone post-merge work share (%)")
    axes[0].set_title("A. Input hotspot by batch")
    axes[1].set_title("B. Hotspot remaining after merge")
    handles, legend_labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, legend_labels, frameon=False, ncol=3, loc="lower center", bbox_to_anchor=(0.5, -0.02))
    fig.tight_layout(rect=(0, 0.10, 1, 1))
    _save(fig, output_dir, "fig3_temporary_hotspots_by_batch", tight=False)

    fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.8))
    axes[0].bar(labels, [row["physical_task_count"] for row in rows], color=colors)
    axes[1].bar(labels, [row["requests_per_physical_task"] for row in rows], color=colors)
    axes[0].set_ylabel("Physical glass services")
    axes[1].set_ylabel("Logical requests per glass service")
    axes[0].set_title("A. Work remaining after batch-wide merge")
    axes[1].set_title("B. Merge effectiveness")
    for ax in axes:
        ax.tick_params(axis="x", rotation=18)
        _style(ax)
    _save(fig, output_dir, "fig4_batch_merge_effect")

    fig, axes = plt.subplots(2, 2, figsize=(9.6, 7.1))
    axes[0, 0].bar(labels, [row["batch_max_zone_work_share_p95"] * 100 for row in rows], color=colors)
    axes[0, 1].bar(labels, [row["capacity_efficiency"] * 100 for row in rows], color=colors)
    axes[1, 0].bar(labels, [row["makespan_h"] for row in rows], color=colors)
    axes[1, 1].bar(labels, [row["latency_p99_h"] for row in rows], color=colors)
    titles = [
        "A. Batches become regionally hot",
        "B. Fixed owners leave resources waiting",
        "C. Sequential batches finish later",
        "D. Hot batches increase tail latency",
    ]
    ylabels = ["P95 busiest-zone work (%)", "Useful capacity (%)", "Completion time (h)", "P99 latency (h)"]
    for ax, title, ylabel in zip(axes.flat, titles, ylabels):
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.tick_params(axis="x", rotation=18)
        _style(ax)
    fig.suptitle("Same trace requests, different batch ordering under strict static zones", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    _save(fig, output_dir, "fig5_multi_batch_research_story", tight=False)


def _load_read_requests(config: TraceBatchSkewConfig) -> list[TraceRequest]:
    requests: list[TraceRequest] = []
    for request in iter_trace(config.trace_path):
        if request.io_type != "R":
            continue
        requests.append(request)
        if len(requests) >= config.max_read_requests:
            break
    if len(requests) < config.max_read_requests:
        raise ValueError(f"trace contains {len(requests)} reads, expected {config.max_read_requests}")
    return requests


def _map_trace_request(config: TraceBatchSkewConfig, request: TraceRequest) -> MappedTraceRequest:
    stripe_id = request.offset // config.placement.stripe_bytes
    platter_id = _hash_u64(stripe_id ^ config.placement.hash_seed) % config.placement.platter_count
    zone_capacity = config.geometry.zone_height_racks * config.geometry.slots_per_half
    zone_id, local_platter = divmod(platter_id, zone_capacity)
    local_level, slot = divmod(local_platter, config.geometry.slots_per_half)
    return MappedTraceRequest(
        source_index=request.index,
        size_bytes=request.size_bytes,
        platter_id=platter_id,
        zone_id=zone_id,
        local_level=local_level,
        slot_in_half=slot,
    )


def _make_panel_batch(
    simulator: PanelStaticZoneSimulator,
    batch: list[MappedTraceRequest],
    global_order_start: int,
) -> list[PanelRequest]:
    return [
        simulator.make_request(
            request_index=global_order_start + order,
            zone_id=request.zone_id,
            local_level=request.local_level,
            slot_in_half=request.slot_in_half,
            size_bytes=request.size_bytes,
        )
        for order, request in enumerate(batch)
    ]


def _panel_config(config: TraceBatchSkewConfig, workload_name: str) -> PanelStaticZoneConfig:
    return PanelStaticZoneConfig(
        output_dir=config.output_dir / "runs" / workload_name,
        seed=config.order_seed,
        geometry=config.geometry,
        movement=config.movement,
        timing=config.timing,
        workload=PanelWorkloadConfig(
            batch_size=config.batch_size,
            request_size_bytes=1,
            placement="uniform_round_robin",
            request_merge=True,
        ),
    )


def _build_batch_rows(
    workload: BatchWorkloadConfig,
    logical_batches: list[list[MappedTraceRequest]],
    merged_batches: list[list[PanelRequest]],
    detail_batches: list[list[PanelRequestDetail]],
    zone_count: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for batch_index, (logical, merged, details) in enumerate(zip(logical_batches, merged_batches, detail_batches)):
        logical_by_zone = [0] * zone_count
        tasks_by_zone = [0] * zone_count
        work_by_zone = [0.0] * zone_count
        for request in logical:
            logical_by_zone[request.zone_id] += 1
        for task in merged:
            tasks_by_zone[task.zone_id] += 1
        for detail in details:
            work_by_zone[detail.zone_id] += detail.cycle_s
        logical_total = len(logical)
        task_total = len(merged)
        active_work_s = sum(work_by_zone)
        start_s = min((detail.arrival_s for detail in details), default=0.0)
        end_s = max((detail.return_done_s for detail in details), default=start_s)
        duration_s = end_s - start_s
        max_work = max(work_by_zone, default=0.0)
        rows.append(
            {
                "workload": workload.name,
                "display_name": workload.display_name,
                "batch_index": batch_index,
                "batch_start_s": start_s,
                "batch_duration_s": duration_s,
                "logical_request_count": logical_total,
                "physical_task_count": task_total,
                "requests_per_physical_task": logical_total / task_total if task_total else 0.0,
                "critical_zone": work_by_zone.index(max_work) if work_by_zone else -1,
                "max_zone_request_share": max(logical_by_zone) / logical_total if logical_total else 0.0,
                "max_zone_task_share": max(tasks_by_zone) / task_total if task_total else 0.0,
                "max_zone_work_share": max_work / active_work_s if active_work_s else 0.0,
                "work_jain_fairness": _jain_fairness(work_by_zone),
                "capacity_efficiency": active_work_s / (zone_count * duration_s) if duration_s else 0.0,
            }
        )
    return rows


def _build_summary_row(
    workload: BatchWorkloadConfig,
    result: PanelStaticZoneResult,
    batch_rows: list[dict[str, Any]],
    signature: str,
) -> dict[str, Any]:
    summary = result.summary
    weighted_latencies = sorted(
        detail.latency_s
        for detail in result.details
        for _ in range(detail.merged_request_count)
    )
    request_shares = sorted(float(row["max_zone_request_share"]) for row in batch_rows)
    work_shares = sorted(float(row["max_zone_work_share"]) for row in batch_rows)
    return {
        "workload": workload.name,
        "display_name": workload.display_name,
        "target_hot_request_fraction": workload.target_hot_request_fraction or 0.0,
        "logical_request_multiset_sha256": signature,
        "batch_count": len(batch_rows),
        "logical_request_count": summary["request_count"],
        "physical_task_count": summary["service_operation_count"],
        "requests_per_physical_task": summary["requests_per_service"],
        "makespan_h": summary["drive_makespan_s"] / 3600,
        "throughput_req_per_s": summary["throughput_req_per_s"],
        "latency_p50_h": _percentile(weighted_latencies, 0.50) / 3600,
        "latency_p95_h": _percentile(weighted_latencies, 0.95) / 3600,
        "latency_p99_h": _percentile(weighted_latencies, 0.99) / 3600,
        "capacity_efficiency": summary["static_capacity_efficiency"],
        "stranded_capacity_share": summary["stranded_capacity_share"],
        "batch_max_zone_request_share_mean": mean(request_shares),
        "batch_max_zone_request_share_p95": _percentile(request_shares, 0.95),
        "batch_max_zone_work_share_mean": mean(work_shares),
        "batch_max_zone_work_share_p95": _percentile(work_shares, 0.95),
        "batch_work_jain_fairness_mean": mean(float(row["work_jain_fairness"]) for row in batch_rows),
        "batch_duration_h_mean": mean(float(row["batch_duration_s"]) for row in batch_rows) / 3600,
        "movement_share": summary["aggregate_component_active_shares"]["shuttle_movement_s"],
        "fixed_share": summary["aggregate_component_active_shares"]["fixed_mechanical_s"],
        "reader_share": summary["aggregate_component_active_shares"]["reader_data_transfer_s"],
    }


def _write_analysis(path: Path, config: TraceBatchSkewConfig, study: TraceBatchSkewResult) -> None:
    rows = [run.summary_row for run in study.runs]
    normal, moderate, severe = rows
    table = [
        "| Workload | P95 busiest-zone requests | P95 busiest-zone work | Physical services | Capacity efficiency | Makespan | Throughput | P99 latency |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        table.append(
            f"| {row['display_name']} | {row['batch_max_zone_request_share_p95'] * 100:.1f}% | "
            f"{row['batch_max_zone_work_share_p95'] * 100:.1f}% | {row['physical_task_count']:.0f} | "
            f"{row['capacity_efficiency'] * 100:.1f}% | {row['makespan_h']:.2f} h | "
            f"{row['throughput_req_per_s']:.3f} req/s | {row['latency_p99_h']:.2f} h |"
        )
    lines = [
        "# Trace-Derived Consecutive Multi-Batch Skew",
        "",
        "## Correct batch semantics",
        "",
        f"- Source: `{config.trace_path}` with {study.source_stats['trace_rows']:,} read requests.",
        f"- Workload: {study.source_stats['batch_count']} consecutive batches, {config.batch_size:,} logical requests per batch.",
        "- Merge scope: the complete current batch. Every request mapped to the same physical glass is combined into one physical glass service, with bytes summed and earliest in-batch order used as priority.",
        "- The same glass may be fetched again in a later batch; merge never crosses a batch boundary.",
        "- Batches execute sequentially: batch N+1 starts after batch N drains.",
        "",
        "## Order-only workload construction",
        "",
        "All workloads contain the exact same trace requests, offsets, sizes, physical mapping, and whole-trace per-zone totals. Only the order used to fill consecutive batches changes.",
        "",
        "1. `Normal`: original timestamp order.",
        "2. `Moderate skew`: each batch targets 50% logical requests from one temporary hot zone.",
        "3. `Severe skew`: each batch targets 80% logical requests from one temporary hot zone.",
        "",
        "The final batches are residual batches: after most zone queues have been consumed, no single zone retains enough requests to sustain the target share. P95 batch skew is used as the primary intensity metric so this finite-trace drain does not redefine the workload.",
        "",
        "Because merge is correctly performed after batch formation, changing batch membership may change merge opportunities. Physical service count is therefore reported explicitly instead of assumed constant.",
        "",
        "## Results",
        "",
        *table,
        "",
        f"Moderate order changes makespan by {moderate['makespan_h'] / normal['makespan_h']:.2f}x and severe order by {severe['makespan_h'] / normal['makespan_h']:.2f}x relative to normal trace order.",
        "",
        "## Interpretation",
        "",
        "A batch becomes slow when most of its post-merge physical work belongs to one static owner. Other shuttle-reader pairs finish their smaller local queues and wait for the batch's critical zone. Since the next batch starts only after the current one drains, unused capacity cannot be recovered by future work.",
        "",
        "The logical hot-request target and post-merge work skew are intentionally shown separately. Many requests to the same glass can merge into one service, so 80% logical-request skew does not automatically mean 80% physical work skew.",
        "",
        "## Evidence boundary",
        "",
        "This experiment models sequential user batches. It does not claim that an online system with overlapping batches must show the same makespan amplification. Online arrivals require a separate no-barrier queueing experiment.",
        "",
        "## Figures",
        "",
        "- `fig1_batch_skew_and_capacity`: batch imbalance and useful capacity.",
        "- `fig2_performance_comparison`: completion time, throughput, and P99 latency.",
        "- `fig3_temporary_hotspots_by_batch`: hotspot movement across batches before and after merge.",
        "- `fig4_batch_merge_effect`: batch-wide merge outcome.",
        "- `fig5_multi_batch_research_story`: high-level paper story.",
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
    return total * total / (len(values) * square_sum) if square_sum else 1.0


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    position = (len(values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    fraction = position - lower
    return values[lower] * (1 - fraction) + values[upper] * fraction


def _chunked(values, size: int):
    return [values[index : index + size] for index in range(0, len(values), size)]


def _resolve_path(value: str, base_dir: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base_dir / path).resolve()


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
    fig.savefig(output_dir / f"{name}.png", dpi=300, bbox_inches="tight", facecolor="white", transparent=False)
    import matplotlib.pyplot as plt

    plt.close(fig)
