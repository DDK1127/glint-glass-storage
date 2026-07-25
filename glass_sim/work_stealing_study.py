from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import csv
import json
import math
import os
from pathlib import Path
import random
from statistics import mean, pstdev
from typing import Any

from .panel_static_zone import PanelGeometryConfig, PanelMovementConfig, PanelTimingConfig
from .paths import portable_path, repository_root_for_config


MIB = 1024 * 1024


@dataclass(frozen=True)
class WorkStealingStudyConfig:
    output_dir: Path
    seeds: tuple[int, ...]
    hotspot_fractions: tuple[float, ...]
    strong_hotspot_fraction: float
    task_count: int
    request_size_bytes: int
    hot_zone: int
    helper_zones: tuple[int, ...]
    geometry: PanelGeometryConfig
    movement: PanelMovementConfig
    timing: PanelTimingConfig

    def validate(self) -> None:
        self.geometry.validate()
        self.movement.validate()
        self.timing.validate()
        zone_count = self.geometry.levels // self.geometry.zone_height_racks * 2
        if zone_count != 8:
            raise ValueError("this focused study requires exactly 8 zones")
        if not self.seeds:
            raise ValueError("seeds cannot be empty")
        if self.task_count <= 0:
            raise ValueError("task_count must be positive")
        if self.request_size_bytes <= 0:
            raise ValueError("request_size_bytes must be positive")
        if not 0 <= self.hot_zone < zone_count:
            raise ValueError("hot_zone must be within the zone count")
        if not self.hotspot_fractions:
            raise ValueError("hotspot_fractions cannot be empty")
        if any(value < 1 / zone_count or value > 1 for value in self.hotspot_fractions):
            raise ValueError("hotspot fractions must be between balanced share and 1")
        if self.strong_hotspot_fraction not in self.hotspot_fractions:
            raise ValueError("strong_hotspot_fraction must be included in hotspot_fractions")
        if not self.helper_zones:
            raise ValueError("helper_zones cannot be empty")
        if any(zone == self.hot_zone or not 0 <= zone < zone_count for zone in self.helper_zones):
            raise ValueError("helper zones must be valid non-hot zones")
        local_capacity = self.geometry.zone_height_racks * self.geometry.slots_per_half
        if round(self.task_count * max(self.hotspot_fractions)) > local_capacity:
            raise ValueError("hot-zone tasks must fit unique physical locations in one zone")

    @property
    def zone_count(self) -> int:
        return self.geometry.levels // self.geometry.zone_height_racks * 2

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "output_dir": portable_path(self.output_dir),
            "seeds": list(self.seeds),
            "hotspot_fractions": list(self.hotspot_fractions),
            "strong_hotspot_fraction": self.strong_hotspot_fraction,
            "task_count": self.task_count,
            "request_size_bytes": self.request_size_bytes,
            "hot_zone": self.hot_zone,
            "helper_zones": list(self.helper_zones),
            "geometry": asdict(self.geometry),
            "movement": asdict(self.movement),
            "timing": asdict(self.timing),
        }


@dataclass(frozen=True)
class GlassTask:
    task_id: int
    owner_zone: int
    level: int
    global_slot: int
    size_bytes: int


@dataclass(frozen=True)
class WorkerState:
    zone_id: int
    reader_level: int
    reader_global_slot: int
    level: int
    global_slot: int
    available_s: float = 0.0


@dataclass(frozen=True)
class ServiceRecord:
    task_id: int
    owner_zone: int
    worker_zone: int
    start_s: float
    drive_done_s: float
    return_done_s: float
    cycle_s: float
    travel_s: float
    horizontal_distance_m: float
    vertical_levels: int
    cross_zone: bool


@dataclass(frozen=True)
class SimulationResult:
    summary: dict[str, Any]
    records: list[ServiceRecord]
    worker_completion_s: dict[int, float]


@dataclass(frozen=True)
class StudyResult:
    static_runs: list[SimulationResult]
    helper_runs: list[SimulationResult]
    run_rows: list[dict[str, Any]]
    aggregate_rows: list[dict[str, Any]]


def load_work_stealing_study_config(path: str | Path) -> WorkStealingStudyConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    base_dir = repository_root_for_config(config_path)
    output_dir = Path(raw["output_dir"])
    if not output_dir.is_absolute():
        output_dir = (base_dir / output_dir).resolve()
    config = WorkStealingStudyConfig(
        output_dir=output_dir,
        seeds=tuple(int(value) for value in raw["seeds"]),
        hotspot_fractions=tuple(float(value) for value in raw["hotspot_fractions"]),
        strong_hotspot_fraction=float(raw["strong_hotspot_fraction"]),
        task_count=int(raw["task_count"]),
        request_size_bytes=int(raw["request_size_bytes"]),
        hot_zone=int(raw["hot_zone"]),
        helper_zones=tuple(int(value) for value in raw["helper_zones"]),
        geometry=PanelGeometryConfig(**raw["geometry"]),
        movement=PanelMovementConfig(**raw["movement"]),
        timing=PanelTimingConfig(**raw["timing"]),
    )
    config.validate()
    return config


def run_work_stealing_study(config: WorkStealingStudyConfig) -> StudyResult:
    static_runs: list[SimulationResult] = []
    helper_runs: list[SimulationResult] = []
    run_rows: list[dict[str, Any]] = []
    for seed in config.seeds:
        for hotspot_fraction in config.hotspot_fractions:
            tasks = generate_tasks(config, hotspot_fraction, seed)
            static = simulate_strict_static(config, tasks)
            static_runs.append(static)
            run_rows.append(_run_row("strict_static", seed, hotspot_fraction, None, static, static))
            if math.isclose(hotspot_fraction, config.strong_hotspot_fraction):
                for helper_zone in config.helper_zones:
                    helper = simulate_one_helper(config, tasks, helper_zone)
                    helper_runs.append(helper)
                    run_rows.append(
                        _run_row(
                            "one_helper",
                            seed,
                            hotspot_fraction,
                            helper_zone,
                            helper,
                            static,
                        )
                    )
    return StudyResult(
        static_runs=static_runs,
        helper_runs=helper_runs,
        run_rows=run_rows,
        aggregate_rows=_aggregate_rows(run_rows),
    )


def generate_tasks(
    config: WorkStealingStudyConfig,
    hotspot_fraction: float,
    seed: int,
) -> dict[int, list[GlassTask]]:
    counts = exact_hotspot_counts(
        config.task_count,
        config.zone_count,
        config.hot_zone,
        hotspot_fraction,
    )
    tasks: dict[int, list[GlassTask]] = {zone: [] for zone in range(config.zone_count)}
    task_id = 0
    local_capacity = config.geometry.zone_height_racks * config.geometry.slots_per_half
    for zone_id in range(config.zone_count):
        locations = list(range(local_capacity))
        random.Random(seed * 1009 + zone_id * 9173).shuffle(locations)
        for local_location in locations[: counts[zone_id]]:
            local_level, local_slot = divmod(local_location, config.geometry.slots_per_half)
            row_id, side = divmod(zone_id, 2)
            level = row_id * config.geometry.zone_height_racks + local_level
            global_slot = _global_slot(side, local_slot, config.geometry.slots_per_half)
            tasks[zone_id].append(
                GlassTask(
                    task_id=task_id,
                    owner_zone=zone_id,
                    level=level,
                    global_slot=global_slot,
                    size_bytes=config.request_size_bytes,
                )
            )
            task_id += 1
    return tasks


def exact_hotspot_counts(
    task_count: int,
    zone_count: int,
    hot_zone: int,
    hotspot_fraction: float,
) -> dict[int, int]:
    hot_count = round(task_count * hotspot_fraction)
    counts = {zone: 0 for zone in range(zone_count)}
    counts[hot_zone] = hot_count
    cold_zones = [zone for zone in range(zone_count) if zone != hot_zone]
    quotient, remainder = divmod(task_count - hot_count, len(cold_zones))
    for index, zone in enumerate(cold_zones):
        counts[zone] = quotient + (1 if index < remainder else 0)
    return counts


def simulate_strict_static(
    config: WorkStealingStudyConfig,
    tasks: dict[int, list[GlassTask]],
) -> SimulationResult:
    states = {zone: _initial_worker(config, zone) for zone in range(config.zone_count)}
    records: list[ServiceRecord] = []
    for zone in range(config.zone_count):
        states[zone], zone_records = _serve_queue(config, states[zone], tasks[zone])
        records.extend(zone_records)
    return _build_result(config, "strict_static", None, records, states)


def simulate_one_helper(
    config: WorkStealingStudyConfig,
    tasks: dict[int, list[GlassTask]],
    helper_zone: int,
) -> SimulationResult:
    states = {zone: _initial_worker(config, zone) for zone in range(config.zone_count)}
    records: list[ServiceRecord] = []

    for zone in range(config.zone_count):
        if zone == config.hot_zone:
            continue
        states[zone], zone_records = _serve_queue(config, states[zone], tasks[zone])
        records.extend(zone_records)

    hot_state = states[config.hot_zone]
    helper_state = states[helper_zone]
    for task in tasks[config.hot_zone]:
        projected_hot_state, hot_record = _serve_task(config, hot_state, task)
        projected_helper_state, helper_record = _serve_task(config, helper_state, task)
        if helper_record.drive_done_s < hot_record.drive_done_s:
            helper_state = projected_helper_state
            records.append(helper_record)
        else:
            hot_state = projected_hot_state
            records.append(hot_record)
    states[config.hot_zone] = hot_state
    states[helper_zone] = helper_state
    return _build_result(config, "one_helper", helper_zone, records, states)


def _serve_queue(
    config: WorkStealingStudyConfig,
    state: WorkerState,
    tasks: list[GlassTask],
) -> tuple[WorkerState, list[ServiceRecord]]:
    records: list[ServiceRecord] = []
    for task in tasks:
        state, record = _serve_task(config, state, task)
        records.append(record)
    return state, records


def _serve_task(
    config: WorkStealingStudyConfig,
    state: WorkerState,
    task: GlassTask,
) -> tuple[WorkerState, ServiceRecord]:
    to_glass = _movement(
        config,
        state.level,
        state.global_slot,
        task.level,
        task.global_slot,
    )
    to_reader = _movement(
        config,
        task.level,
        task.global_slot,
        state.reader_level,
        state.reader_global_slot,
    )
    return_move = _movement(
        config,
        state.reader_level,
        state.reader_global_slot,
        task.level,
        task.global_slot,
    )
    read_s = (
        config.timing.reader_mount_s
        + config.timing.reader_base_s
        + (task.size_bytes / MIB) / config.timing.reader_mib_per_s
    )
    drive_done_s = (
        state.available_s
        + to_glass[0]
        + config.timing.storage_pick_s
        + to_reader[0]
        + config.timing.reader_load_s
        + read_s
    )
    return_done_s = (
        drive_done_s
        + config.timing.reader_unload_s
        + return_move[0]
        + config.timing.storage_place_s
    )
    new_state = replace(
        state,
        level=task.level,
        global_slot=task.global_slot,
        available_s=return_done_s,
    )
    travel_s = to_glass[0] + to_reader[0] + return_move[0]
    record = ServiceRecord(
        task_id=task.task_id,
        owner_zone=task.owner_zone,
        worker_zone=state.zone_id,
        start_s=state.available_s,
        drive_done_s=drive_done_s,
        return_done_s=return_done_s,
        cycle_s=return_done_s - state.available_s,
        travel_s=travel_s,
        horizontal_distance_m=to_glass[1] + to_reader[1] + return_move[1],
        vertical_levels=to_glass[2] + to_reader[2] + return_move[2],
        cross_zone=state.zone_id != task.owner_zone,
    )
    return new_state, record


def _build_result(
    config: WorkStealingStudyConfig,
    policy: str,
    helper_zone: int | None,
    records: list[ServiceRecord],
    states: dict[int, WorkerState],
) -> SimulationResult:
    makespan_s = max((record.drive_done_s for record in records), default=0.0)
    system_drain_s = max((state.available_s for state in states.values()), default=0.0)
    productive_s = sum(record.cycle_s for record in records)
    helper_records = [record for record in records if record.cross_zone]
    helper_distance_s = (
        _zone_center_travel_s(config, helper_zone, config.hot_zone)
        if helper_zone is not None
        else 0.0
    )
    helper_route_hops = (
        _zone_hops(helper_zone, config.hot_zone) if helper_zone is not None else 0
    )
    summary = {
        "policy": policy,
        "helper_zone": helper_zone,
        "task_count": len(records),
        "makespan_s": makespan_s,
        "system_drain_s": system_drain_s,
        "productive_cycle_s": productive_s,
        "capacity_efficiency": productive_s / (config.zone_count * system_drain_s)
        if system_drain_s > 0
        else 0.0,
        "stranded_capacity_share": 1.0
        - productive_s / (config.zone_count * system_drain_s)
        if system_drain_s > 0
        else 0.0,
        "total_travel_s": sum(record.travel_s for record in records),
        "horizontal_distance_m": sum(record.horizontal_distance_m for record in records),
        "vertical_levels": sum(record.vertical_levels for record in records),
        "stolen_task_count": len(helper_records),
        "stolen_task_travel_s": sum(record.travel_s for record in helper_records),
        "helper_first_stolen_start_s": helper_records[0].start_s if helper_records else 0.0,
        "helper_first_stolen_cycle_s": helper_records[0].cycle_s if helper_records else 0.0,
        "helper_home_to_hot_center_s": helper_distance_s,
        "helper_route_hops": helper_route_hops,
        "assumptions": [
            "The panel has 8 fixed zones arranged as 4 rows x 2 sides.",
            "Each zone has one shuttle and one local reader.",
            "A helper finishes its local queue before stealing hot-zone tasks.",
            "A helper carries a stolen platter to its own local reader and returns it to its original slot.",
            "Hot tasks are greedily assigned to the local owner or one fixed helper by projected drive completion time.",
            "Cross-zone movement time is modeled, but route conflicts and collision waiting are not yet modeled.",
        ],
    }
    return SimulationResult(
        summary=summary,
        records=records,
        worker_completion_s={zone: state.available_s for zone, state in states.items()},
    )


def _initial_worker(config: WorkStealingStudyConfig, zone_id: int) -> WorkerState:
    row_id, side = divmod(zone_id, 2)
    row_start = row_id * config.geometry.zone_height_racks
    reader_level = min(
        row_start + config.geometry.zone_height_racks // 2,
        config.geometry.levels - 1,
    )
    reader_local_slot = 0 if side == 0 else config.geometry.slots_per_half - 1
    reader_global_slot = _global_slot(side, reader_local_slot, config.geometry.slots_per_half)
    return WorkerState(
        zone_id=zone_id,
        reader_level=reader_level,
        reader_global_slot=reader_global_slot,
        level=reader_level,
        global_slot=reader_global_slot,
    )


def _global_slot(side: int, local_slot: int, slots_per_half: int) -> int:
    return local_slot if side == 0 else slots_per_half + local_slot


def _movement(
    config: WorkStealingStudyConfig,
    source_level: int,
    source_slot: int,
    target_level: int,
    target_slot: int,
) -> tuple[float, float, int]:
    vertical_levels = abs(target_level - source_level)
    vertical_s = vertical_levels * config.movement.vertical_s_per_level
    slot_width_m = config.geometry.half_panel_length_m / (config.geometry.slots_per_half - 1)
    horizontal_m = abs(target_slot - source_slot) * slot_width_m
    horizontal_s = _horizontal_time_s(config.movement, horizontal_m)
    return vertical_s + horizontal_s, horizontal_m, vertical_levels


def _horizontal_time_s(movement: PanelMovementConfig, distance_m: float) -> float:
    if distance_m <= 0:
        return 0.0
    acceleration_distance = movement.horizontal_max_m_s**2 / movement.horizontal_accel_m_s2
    if distance_m <= acceleration_distance:
        travel_s = 2.0 * math.sqrt(distance_m / movement.horizontal_accel_m_s2)
    else:
        travel_s = (
            2.0 * movement.horizontal_max_m_s / movement.horizontal_accel_m_s2
            + (distance_m - acceleration_distance) / movement.horizontal_max_m_s
        )
    return max(movement.horizontal_min_s, travel_s)


def _zone_center_travel_s(
    config: WorkStealingStudyConfig,
    source_zone: int,
    target_zone: int,
) -> float:
    source_row, source_side = divmod(source_zone, 2)
    target_row, target_side = divmod(target_zone, 2)
    local_center = (config.geometry.slots_per_half - 1) // 2
    source_slot = _global_slot(source_side, local_center, config.geometry.slots_per_half)
    target_slot = _global_slot(target_side, local_center, config.geometry.slots_per_half)
    source_level = source_row * config.geometry.zone_height_racks + config.geometry.zone_height_racks // 2
    target_level = target_row * config.geometry.zone_height_racks + config.geometry.zone_height_racks // 2
    return _movement(config, source_level, source_slot, target_level, target_slot)[0]


def _zone_hops(source_zone: int, target_zone: int) -> int:
    source_row, source_side = divmod(source_zone, 2)
    target_row, target_side = divmod(target_zone, 2)
    return abs(source_row - target_row) + abs(source_side - target_side)


def _run_row(
    policy: str,
    seed: int,
    hotspot_fraction: float,
    helper_zone: int | None,
    result: SimulationResult,
    strict: SimulationResult,
) -> dict[str, Any]:
    summary = result.summary
    strict_summary = strict.summary
    return {
        "policy": policy,
        "seed": seed,
        "hotspot_fraction": hotspot_fraction,
        "helper_zone": -1 if helper_zone is None else helper_zone,
        "helper_route_hops": summary["helper_route_hops"],
        "helper_home_to_hot_center_s": summary["helper_home_to_hot_center_s"],
        "task_count": summary["task_count"],
        "makespan_s": summary["makespan_s"],
        "system_drain_s": summary["system_drain_s"],
        "capacity_efficiency": summary["capacity_efficiency"],
        "stranded_capacity_share": summary["stranded_capacity_share"],
        "total_travel_s": summary["total_travel_s"],
        "horizontal_distance_m": summary["horizontal_distance_m"],
        "vertical_levels": summary["vertical_levels"],
        "stolen_task_count": summary["stolen_task_count"],
        "stolen_task_travel_s": summary["stolen_task_travel_s"],
        "helper_first_stolen_start_s": summary["helper_first_stolen_start_s"],
        "helper_first_stolen_cycle_s": summary["helper_first_stolen_cycle_s"],
        "makespan_reduction_s": strict_summary["makespan_s"] - summary["makespan_s"],
        "makespan_reduction_fraction": (
            (strict_summary["makespan_s"] - summary["makespan_s"]) / strict_summary["makespan_s"]
            if strict_summary["makespan_s"] > 0
            else 0.0
        ),
        "extra_travel_s": summary["total_travel_s"] - strict_summary["total_travel_s"],
    }


def _aggregate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, float, int], list[dict[str, Any]]] = {}
    for row in rows:
        key = (row["policy"], row["hotspot_fraction"], row["helper_zone"])
        groups.setdefault(key, []).append(row)
    identity = {"policy", "seed", "hotspot_fraction", "helper_zone"}
    aggregates: list[dict[str, Any]] = []
    for key, group in sorted(groups.items()):
        aggregate: dict[str, Any] = {
            "policy": key[0],
            "hotspot_fraction": key[1],
            "helper_zone": key[2],
            "run_count": len(group),
        }
        for field in group[0]:
            if field in identity:
                continue
            values = [float(row[field]) for row in group]
            aggregate[f"{field}_mean"] = mean(values)
            aggregate[f"{field}_std"] = pstdev(values) if len(values) > 1 else 0.0
        aggregates.append(aggregate)
    return aggregates


def write_work_stealing_study_outputs(
    config: WorkStealingStudyConfig,
    study: StudyResult,
) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    _write_rows(config.output_dir / "run_summary.csv", study.run_rows)
    _write_rows(config.output_dir / "aggregate_summary.csv", study.aggregate_rows)
    with (config.output_dir / "config.json").open("w", encoding="utf-8") as handle:
        json.dump(config.to_json_dict(), handle, indent=2)
        handle.write("\n")
    findings = _build_findings(config, study.aggregate_rows)
    with (config.output_dir / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "config": config.to_json_dict(),
                "findings": findings,
                "model_scope": {
                    "modeled": [
                        "8 fixed zones",
                        "single-zone hotspot",
                        "one fixed helper",
                        "cross-zone movement time",
                        "helper-local reader service",
                        "return to original glass slot",
                    ],
                    "not_modeled": [
                        "route conflicts",
                        "collision waiting",
                        "multiple-helper ingress congestion",
                        "online threshold oscillation",
                    ],
                },
            },
            handle,
            indent=2,
        )
        handle.write("\n")
    _write_analysis(config, findings, config.output_dir / "STATIC_ZONE_WORK_STEALING_MOTIVATION.md")
    figures_dir = config.output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    write_work_stealing_study_figures(config, study, figures_dir)


def _build_findings(
    config: WorkStealingStudyConfig,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    static_rows = sorted(
        (row for row in rows if row["policy"] == "strict_static"),
        key=lambda row: row["hotspot_fraction"],
    )
    helper_rows = sorted(
        (row for row in rows if row["policy"] == "one_helper"),
        key=lambda row: row["helper_home_to_hot_center_s_mean"],
    )
    balanced = static_rows[0]
    strong = next(
        row
        for row in static_rows
        if math.isclose(row["hotspot_fraction"], config.strong_hotspot_fraction)
    )
    return {
        "static_hotspot": {
            "balanced_fraction": balanced["hotspot_fraction"],
            "strong_fraction": strong["hotspot_fraction"],
            "balanced_makespan_h": balanced["makespan_s_mean"] / 3600.0,
            "strong_makespan_h": strong["makespan_s_mean"] / 3600.0,
            "makespan_ratio": strong["makespan_s_mean"] / balanced["makespan_s_mean"],
            "balanced_capacity_efficiency": balanced["capacity_efficiency_mean"],
            "strong_capacity_efficiency": strong["capacity_efficiency_mean"],
            "strong_stranded_capacity_share": strong["stranded_capacity_share_mean"],
        },
        "one_helper_distance": [
            {
                "helper_zone": int(row["helper_zone"]),
                "route_hops": row["helper_route_hops_mean"],
                "home_to_hot_center_s": row["helper_home_to_hot_center_s_mean"],
                "stolen_tasks": row["stolen_task_count_mean"],
                "makespan_h": row["makespan_s_mean"] / 3600.0,
                "makespan_reduction_fraction": row["makespan_reduction_fraction_mean"],
                "extra_travel_h": row["extra_travel_s_mean"] / 3600.0,
            }
            for row in helper_rows
        ],
    }


def write_work_stealing_study_figures(
    config: WorkStealingStudyConfig,
    study: StudyResult,
    figures_dir: Path,
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(Path("results/.mplconfig").resolve()))
    os.environ.setdefault("XDG_CACHE_HOME", str(Path("results/.cache").resolve()))
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
    _plot_static_hotspot(config, study.aggregate_rows, figures_dir, plt)
    _plot_static_zone_timeline(config, figures_dir, plt)
    _plot_helper_distance(config, study.aggregate_rows, figures_dir, plt)
    _plot_stealing_tradeoff(config, study.aggregate_rows, figures_dir, plt)


def _plot_static_hotspot(config, rows, output_dir, plt) -> None:
    series = sorted(
        (row for row in rows if row["policy"] == "strict_static"),
        key=lambda row: row["hotspot_fraction"],
    )
    x = [row["hotspot_fraction"] * 100 for row in series]
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.5))
    axes[0].errorbar(
        x,
        [row["makespan_s_mean"] / 3600.0 for row in series],
        yerr=[row["makespan_s_std"] / 3600.0 for row in series],
        color="#C84C4C",
        marker="o",
        linewidth=2,
        capsize=3,
    )
    axes[1].errorbar(
        x,
        [row["capacity_efficiency_mean"] * 100 for row in series],
        yerr=[row["capacity_efficiency_std"] * 100 for row in series],
        color="#2F6B9A",
        marker="s",
        linewidth=2,
        capsize=3,
    )
    axes[0].set_ylabel("Batch makespan (h)")
    axes[1].set_ylabel("Useful zone-time capacity (%)")
    axes[0].set_title("A hotspot stretches the fixed owner's queue")
    axes[1].set_title("Other fixed-zone resources become idle")
    for ax in axes:
        ax.set_xlabel("Zone 0 share of active glass tasks (%)")
        ax.set_xticks(x)
        _style(ax)
    _save(fig, output_dir, "fig1_static_hotspot_motivation")


def _plot_static_zone_timeline(config, output_dir, plt) -> None:
    first_seed = config.seeds[0]
    fractions = [min(config.hotspot_fractions), config.strong_hotspot_fraction]
    results = [
        simulate_strict_static(config, generate_tasks(config, fraction, first_seed))
        for fraction in fractions
    ]
    fig, axes = plt.subplots(1, 2, figsize=(9.3, 3.8), sharey=True)
    for ax, result, fraction in zip(axes, results, fractions):
        zone_ids = list(range(config.zone_count))
        completion_h = [result.worker_completion_s[zone] / 3600.0 for zone in zone_ids]
        drain_h = result.summary["system_drain_s"] / 3600.0
        idle_h = [max(0.0, drain_h - value) for value in completion_h]
        ax.barh(zone_ids, completion_h, color="#2F6B9A", label="Serving local queue")
        ax.barh(zone_ids, idle_h, left=completion_h, color="#D7DEE8", label="Idle while panel drains")
        ax.set_title(f"Zone 0 owns {fraction * 100:.1f}% of active tasks")
        ax.set_xlabel("Time from batch start (h)")
        ax.set_yticks(zone_ids)
        ax.invert_yaxis()
        ax.grid(True, axis="x", color="#D7DEE8", linewidth=0.7, zorder=0)
        ax.grid(False, axis="y")
        for spine in ["top", "right"]:
            ax.spines[spine].set_visible(False)
    axes[0].set_ylabel("Fixed zone")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, loc="lower center", ncol=2)
    fig.suptitle("Hot-zone backlog coexists with idle resources", fontsize=12)
    fig.tight_layout(rect=(0, 0.08, 1, 0.94))
    _save(fig, output_dir, "fig2_static_zone_timeline", tight=False)


def _plot_helper_distance(config, rows, output_dir, plt) -> None:
    strict = next(
        row
        for row in rows
        if row["policy"] == "strict_static"
        and math.isclose(row["hotspot_fraction"], config.strong_hotspot_fraction)
    )
    helpers = sorted(
        (row for row in rows if row["policy"] == "one_helper"),
        key=lambda row: row["helper_home_to_hot_center_s_mean"],
    )
    labels = [
        f"Zone {int(row['helper_zone'])}\n{row['helper_home_to_hot_center_s_mean']:.1f}s away"
        for row in helpers
    ]
    x = list(range(len(helpers)))
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.7))
    axes[0].bar(
        x,
        [row["makespan_s_mean"] / 3600.0 for row in helpers],
        yerr=[row["makespan_s_std"] / 3600.0 for row in helpers],
        color="#2F6B9A",
        capsize=3,
    )
    axes[0].axhline(
        strict["makespan_s_mean"] / 3600.0,
        color="#C84C4C",
        linestyle="--",
        linewidth=1.5,
        label="No stealing",
    )
    axes[1].bar(
        x,
        [row["extra_travel_s_mean"] / 3600.0 for row in helpers],
        yerr=[row["extra_travel_s_std"] / 3600.0 for row in helpers],
        color="#D9822B",
        capsize=3,
    )
    axes[0].set_ylabel("Batch makespan (h)")
    axes[1].set_ylabel("Extra aggregate travel time (h)")
    axes[0].set_title("One helper reduces the hot-zone bottleneck")
    axes[1].set_title("Longer assistance requires more movement")
    for ax in axes:
        ax.set_xticks(x, labels)
        ax.set_xlabel("Fixed helper and center-to-center distance")
        _style(ax)
    axes[0].legend(frameon=False, loc="upper left")
    _save(fig, output_dir, "fig3_helper_distance")


def _plot_stealing_tradeoff(config, rows, output_dir, plt) -> None:
    helpers = sorted(
        (row for row in rows if row["policy"] == "one_helper"),
        key=lambda row: row["helper_home_to_hot_center_s_mean"],
    )
    fig, ax = plt.subplots(figsize=(6.8, 4.2))
    label_offsets = {2: (8, -24), 1: (8, 8), 4: (8, 8), 7: (8, 8)}
    for row in helpers:
        x = row["extra_travel_s_mean"] / 3600.0
        y = row["makespan_reduction_fraction_mean"] * 100
        ax.errorbar(
            x,
            y,
            xerr=row["extra_travel_s_std"] / 3600.0,
            yerr=row["makespan_reduction_fraction_std"] * 100,
            fmt="o",
            markersize=7,
            color="#2F6B9A",
            capsize=3,
        )
        helper_zone = int(row["helper_zone"])
        ax.annotate(
            f"Zone {helper_zone}\n{row['helper_home_to_hot_center_s_mean']:.1f}s away",
            (x, y),
            xytext=label_offsets[helper_zone],
            textcoords="offset points",
            fontsize=8,
        )
    ax.set_xlabel("Extra aggregate shuttle travel time (h)")
    ax.set_ylabel("Makespan reduction vs. strict static (%)")
    ax.set_title("Work stealing trades load balance for cross-zone movement", pad=12)
    _style(ax)
    _save(fig, output_dir, "fig4_work_stealing_tradeoff")


def _write_analysis(
    config: WorkStealingStudyConfig,
    findings: dict[str, Any],
    path: Path,
) -> None:
    static = findings["static_hotspot"]
    helpers = findings["one_helper_distance"]
    nearest = helpers[0]
    farthest = helpers[-1]
    lines = [
        "# Static-Zone Hotspot and Work-Stealing Motivation",
        "",
        "## Purpose",
        "",
        "This focused 8-zone study establishes the motivation in two steps: first, it shows how a single-zone hotspot strands resources under strict fixed ownership; second, it measures the movement cost of assigning one cold-zone helper to the hot zone.",
        "",
        "## Observation 1: a hotspot creates fixed-owner imbalance",
        "",
        f"The balanced workload assigns {static['balanced_fraction'] * 100:.1f}% of active glass tasks to Zone 0 and completes in {static['balanced_makespan_h']:.2f} h with {static['balanced_capacity_efficiency'] * 100:.1f}% useful zone-time capacity.",
        f"When Zone 0 owns {static['strong_fraction'] * 100:.1f}% of the same-size task batch, completion grows to {static['strong_makespan_h']:.2f} h ({static['makespan_ratio']:.2f}x) and {static['strong_stranded_capacity_share'] * 100:.1f}% of zone-time capacity is idle while the panel drains.",
        "",
        "> The panel does not lack aggregate resources; strict ownership prevents non-owning resources from serving the hot queue.",
        "",
        "## Observation 2: one helper restores parallelism at a movement cost",
        "",
        f"The nearest evaluated helper is Zone {nearest['helper_zone']} ({nearest['home_to_hot_center_s']:.1f}s center-to-center travel). It steals {nearest['stolen_tasks']:.1f} tasks on average, reduces makespan by {nearest['makespan_reduction_fraction'] * 100:.1f}%, and adds {nearest['extra_travel_h']:.2f} h of aggregate shuttle travel.",
        f"The farthest evaluated helper is Zone {farthest['helper_zone']} ({farthest['home_to_hot_center_s']:.1f}s center-to-center travel). It reduces makespan by {farthest['makespan_reduction_fraction'] * 100:.1f}% while adding {farthest['extra_travel_h']:.2f} h of aggregate shuttle travel.",
        "",
        "The helper results should be interpreted as a collision-free movement baseline. They show the direct travel burden of remote assistance, but do not yet include waiting imposed on intermediate zones or congestion caused by multiple helpers entering the hotspot.",
        "",
        "## Motivation transition",
        "",
        "Static zones provide predictable local traffic, but a hotspot ties completion to one owner. Work stealing can use idle capacity, yet the helper must repeatedly carry hot-zone platters across fixed service regions. This creates the next research question: how should the controller select and bound helpers so that completion-time gains justify the added cross-zone movement and interference risk?",
        "",
        "## Figure guide",
        "",
        "- `fig1_static_hotspot_motivation`: hotspot strength versus makespan and useful capacity.",
        "- `fig2_static_zone_timeline`: per-zone work and idle intervals for balanced and strong-hotspot workloads.",
        "- `fig3_helper_distance`: one-helper completion benefit and added travel by helper location.",
        "- `fig4_work_stealing_tradeoff`: completion-time gain versus added shuttle travel.",
        "",
        "## Evidence boundaries",
        "",
        "- Workloads are controlled synthetic batches of unique glass tasks.",
        "- A helper finishes its own queue, uses its local reader for stolen platters, and returns each platter to its original slot.",
        "- Hot tasks are assigned greedily between the local owner and one fixed helper.",
        "- Cross-zone travel time is modeled using the panel movement parameters.",
        "- Route conflicts, collision waiting, intermediate-zone interference, and multi-helper ingress congestion are not modeled.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


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


def _save(fig, output_dir: Path, name: str, tight: bool = True) -> None:
    if tight:
        fig.tight_layout()
    fig.savefig(output_dir / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(output_dir / f"{name}.png", dpi=300, bbox_inches="tight")
    import matplotlib.pyplot as plt

    plt.close(fig)
