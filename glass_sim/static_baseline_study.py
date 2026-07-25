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

from .panel_static_zone import (
    PanelGeometryConfig,
    PanelMovementConfig,
    PanelRequest,
    PanelStaticZoneConfig,
    PanelStaticZoneResult,
    PanelStaticZoneSimulator,
    PanelTimingConfig,
    PanelWorkloadConfig,
    merge_panel_requests,
    write_panel_static_zone_outputs,
)
from .paths import portable_path, repository_root_for_config


MIB = 1024 * 1024


@dataclass(frozen=True)
class StaticBaselineStudyWorkloadConfig:
    batch_size: int
    request_size_bytes: int
    hot_zone: int = 0

    def validate(self) -> None:
        if self.batch_size <= 0:
            raise ValueError("workload.batch_size must be positive")
        if self.request_size_bytes <= 0:
            raise ValueError("workload.request_size_bytes must be positive")
        if self.hot_zone < 0:
            raise ValueError("workload.hot_zone cannot be negative")


@dataclass(frozen=True)
class StaticBaselineStudyConfig:
    output_dir: Path
    seeds: tuple[int, ...]
    hot_zone_fractions: tuple[float, ...]
    primary_hotspot_width: int
    hotspot_widths: tuple[int, ...]
    width_sensitivity_hot_fraction: float
    active_zone_counts: tuple[int, ...]
    active_task_count: int
    merge_modes: tuple[bool, ...]
    write_representative_details: bool
    geometry: PanelGeometryConfig
    movement: PanelMovementConfig
    timing: PanelTimingConfig
    workload: StaticBaselineStudyWorkloadConfig

    def validate(self) -> None:
        self.geometry.validate()
        self.movement.validate()
        self.timing.validate()
        self.workload.validate()
        if not self.seeds:
            raise ValueError("seeds cannot be empty")
        if not self.hot_zone_fractions:
            raise ValueError("hot_zone_fractions cannot be empty")
        if not self.hotspot_widths:
            raise ValueError("hotspot_widths cannot be empty")
        if not self.active_zone_counts:
            raise ValueError("active_zone_counts cannot be empty")
        if not self.merge_modes:
            raise ValueError("merge_modes cannot be empty")
        zone_count = self.geometry.levels // self.geometry.zone_height_racks * 2
        if self.workload.hot_zone >= zone_count:
            raise ValueError("workload.hot_zone must be within the panel zone count")
        if not 1 <= self.primary_hotspot_width <= zone_count:
            raise ValueError("primary_hotspot_width must be within the panel zone count")
        if any(width <= 0 or width > zone_count for width in self.hotspot_widths):
            raise ValueError("every hotspot width must be within the panel zone count")
        if any(count <= 0 or count > zone_count for count in self.active_zone_counts):
            raise ValueError("every active zone count must be within the panel zone count")
        local_capacity = self.geometry.zone_height_racks * self.geometry.slots_per_half
        if self.active_task_count <= 0 or self.active_task_count > local_capacity:
            raise ValueError("active_task_count must be positive and fit within one zone")
        if any(fraction < 0.0 or fraction > 1.0 for fraction in self.hot_zone_fractions):
            raise ValueError("hot_zone_fractions must be between 0 and 1")
        if not 0.0 <= self.width_sensitivity_hot_fraction <= 1.0:
            raise ValueError("width_sensitivity_hot_fraction must be between 0 and 1")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "output_dir": portable_path(self.output_dir),
            "seeds": list(self.seeds),
            "hot_zone_fractions": list(self.hot_zone_fractions),
            "primary_hotspot_width": self.primary_hotspot_width,
            "hotspot_widths": list(self.hotspot_widths),
            "width_sensitivity_hot_fraction": self.width_sensitivity_hot_fraction,
            "active_zone_counts": list(self.active_zone_counts),
            "active_task_count": self.active_task_count,
            "merge_modes": list(self.merge_modes),
            "write_representative_details": self.write_representative_details,
            "geometry": asdict(self.geometry),
            "movement": asdict(self.movement),
            "timing": asdict(self.timing),
            "workload": asdict(self.workload),
        }


@dataclass(frozen=True)
class StaticBaselineStudyRun:
    scenario: str
    seed: int
    hot_zone_fraction: float
    hotspot_width: int
    request_merge: bool
    panel_config: PanelStaticZoneConfig
    result: PanelStaticZoneResult
    run_row: dict[str, Any]


@dataclass(frozen=True)
class StaticBaselineStudyResult:
    runs: list[StaticBaselineStudyRun]
    aggregate_rows: list[dict[str, Any]]
    zone_rows: list[dict[str, Any]]


def load_static_baseline_study_config(path: str | Path) -> StaticBaselineStudyConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    base_dir = repository_root_for_config(config_path)
    config = StaticBaselineStudyConfig(
        output_dir=_resolve_path(raw["output_dir"], base_dir),
        seeds=tuple(int(value) for value in raw["seeds"]),
        hot_zone_fractions=tuple(float(value) for value in raw["hot_zone_fractions"]),
        primary_hotspot_width=int(raw["primary_hotspot_width"]),
        hotspot_widths=tuple(int(value) for value in raw["hotspot_widths"]),
        width_sensitivity_hot_fraction=float(raw["width_sensitivity_hot_fraction"]),
        active_zone_counts=tuple(int(value) for value in raw["active_zone_counts"]),
        active_task_count=int(raw["active_task_count"]),
        merge_modes=tuple(bool(value) for value in raw["merge_modes"]),
        write_representative_details=bool(raw.get("write_representative_details", True)),
        geometry=PanelGeometryConfig(**raw["geometry"]),
        movement=PanelMovementConfig(**raw["movement"]),
        timing=PanelTimingConfig(**raw["timing"]),
        workload=StaticBaselineStudyWorkloadConfig(**raw["workload"]),
    )
    config.validate()
    return config


def run_static_baseline_study(config: StaticBaselineStudyConfig) -> StaticBaselineStudyResult:
    runs: list[StaticBaselineStudyRun] = []
    zone_rows: list[dict[str, Any]] = []
    for scenario, hot_fraction, hotspot_width in _run_specs(config):
        for request_merge in config.merge_modes:
            for seed in config.seeds:
                batch_size = (
                    config.active_task_count
                    if scenario == "active_zone_concentration"
                    else config.workload.batch_size
                )
                panel_config = _panel_config_for_run(
                    config,
                    scenario=scenario,
                    seed=seed,
                    hot_fraction=hot_fraction,
                    hotspot_width=hotspot_width,
                    request_merge=request_merge,
                    batch_size=batch_size,
                )
                simulator = PanelStaticZoneSimulator(panel_config)
                if scenario == "active_zone_concentration":
                    requests = generate_paired_active_tasks(
                        simulator,
                        task_count=config.active_task_count,
                        request_size_bytes=config.workload.request_size_bytes,
                        first_zone=config.workload.hot_zone,
                        active_zone_count=hotspot_width,
                        seed=seed,
                    )
                else:
                    requests = generate_paired_requests(
                        simulator,
                        batch_size=config.workload.batch_size,
                        request_size_bytes=config.workload.request_size_bytes,
                        hot_zone=config.workload.hot_zone,
                        hot_zone_fraction=hot_fraction,
                        hotspot_width=hotspot_width,
                        seed=seed,
                    )
                if request_merge:
                    requests = merge_panel_requests(requests)
                result = simulator.run(requests)
                run_row = _build_run_row(
                    scenario=scenario,
                    seed=seed,
                    hot_fraction=hot_fraction,
                    hotspot_width=hotspot_width,
                    request_merge=request_merge,
                    result=result,
                )
                run = StaticBaselineStudyRun(
                    scenario=scenario,
                    seed=seed,
                    hot_zone_fraction=hot_fraction,
                    hotspot_width=hotspot_width,
                    request_merge=request_merge,
                    panel_config=panel_config,
                    result=result,
                    run_row=run_row,
                )
                runs.append(run)
                zone_rows.extend(_annotate_zone_rows(run))
    return StaticBaselineStudyResult(
        runs=runs,
        aggregate_rows=_aggregate_runs([run.run_row for run in runs]),
        zone_rows=zone_rows,
    )


def generate_paired_requests(
    simulator: PanelStaticZoneSimulator,
    batch_size: int,
    request_size_bytes: int,
    hot_zone: int,
    hot_zone_fraction: float,
    hotspot_width: int,
    seed: int,
) -> list[PanelRequest]:
    zone_ids = exact_zone_assignment(
        batch_size=batch_size,
        zone_count=simulator.zone_count,
        hot_zone=hot_zone,
        hot_zone_fraction=hot_zone_fraction,
        hotspot_width=hotspot_width,
        seed=seed + 101,
    )
    location_rng = random.Random(seed + 2909)
    requests: list[PanelRequest] = []
    for request_index, zone_id in enumerate(zone_ids):
        local_level = location_rng.randrange(simulator.geometry.zone_height_racks)
        slot_in_half = location_rng.randrange(simulator.geometry.slots_per_half)
        requests.append(
            simulator.make_request(
                request_index=request_index,
                zone_id=zone_id,
                local_level=local_level,
                slot_in_half=slot_in_half,
                size_bytes=request_size_bytes,
            )
        )
    return requests


def generate_paired_active_tasks(
    simulator: PanelStaticZoneSimulator,
    task_count: int,
    request_size_bytes: int,
    first_zone: int,
    active_zone_count: int,
    seed: int,
) -> list[PanelRequest]:
    """Create the same unique local glass tasks under different fixed-zone concentrations."""
    local_capacity = simulator.geometry.zone_height_racks * simulator.geometry.slots_per_half
    if task_count > local_capacity:
        raise ValueError("task_count must fit within one zone to preserve unique paired locations")
    if not 1 <= active_zone_count <= simulator.zone_count:
        raise ValueError("active_zone_count must be within the panel zone count")

    local_locations = list(range(local_capacity))
    random.Random(seed + 2909).shuffle(local_locations)
    active_zones = [
        (first_zone + offset) % simulator.zone_count for offset in range(active_zone_count)
    ]
    requests: list[PanelRequest] = []
    for task_index, local_location in enumerate(local_locations[:task_count]):
        zone_id = active_zones[task_index % active_zone_count]
        local_level, slot_in_half = divmod(
            local_location,
            simulator.geometry.slots_per_half,
        )
        requests.append(
            simulator.make_request(
                request_index=task_index,
                zone_id=zone_id,
                local_level=local_level,
                slot_in_half=slot_in_half,
                size_bytes=request_size_bytes,
            )
        )
    return requests


def exact_zone_assignment(
    batch_size: int,
    zone_count: int,
    hot_zone: int,
    hot_zone_fraction: float,
    hotspot_width: int,
    seed: int,
) -> list[int]:
    hot_zones = [(hot_zone + offset) % zone_count for offset in range(hotspot_width)]
    hot_set = set(hot_zones)
    cold_zones = [zone_id for zone_id in range(zone_count) if zone_id not in hot_set]
    if not cold_zones:
        hot_count = batch_size
    else:
        hot_count = min(batch_size, max(0, round(batch_size * hot_zone_fraction)))
    counts = {zone_id: 0 for zone_id in range(zone_count)}
    _distribute_exact(hot_count, hot_zones, counts)
    _distribute_exact(batch_size - hot_count, cold_zones or hot_zones, counts)
    zone_ids = [zone_id for zone_id in range(zone_count) for _ in range(counts[zone_id])]
    rng = random.Random(seed)
    rng.shuffle(zone_ids)
    return zone_ids


def write_static_baseline_study_outputs(
    config: StaticBaselineStudyConfig,
    study: StaticBaselineStudyResult,
) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    _write_rows(config.output_dir / "run_summary.csv", [run.run_row for run in study.runs])
    _write_rows(config.output_dir / "aggregate_summary.csv", study.aggregate_rows)
    _write_rows(config.output_dir / "zone_detail.csv", study.zone_rows)
    with (config.output_dir / "config.json").open("w", encoding="utf-8") as handle:
        json.dump(config.to_json_dict(), handle, indent=2)
        handle.write("\n")
    findings = _build_findings(config, study)
    with (config.output_dir / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "config": config.to_json_dict(),
                "run_count": len(study.runs),
                "aggregate_count": len(study.aggregate_rows),
                "findings": findings,
            },
            handle,
            indent=2,
        )
        handle.write("\n")
    _write_analysis(config.output_dir / "STATIC_BASELINE_BOTTLENECK_ANALYSIS.md", config, study, findings)
    if config.write_representative_details:
        _write_representative_outputs(config, study)
    figures_dir = config.output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    write_static_baseline_study_figures(config, study, figures_dir)


def write_static_baseline_study_figures(
    config: StaticBaselineStudyConfig,
    study: StaticBaselineStudyResult,
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
    _plot_performance_vs_skew(config, study.aggregate_rows, figures_dir, plt)
    _plot_ownership_imbalance(config, study.aggregate_rows, figures_dir, plt)
    _plot_stranded_capacity(config, study.aggregate_rows, figures_dir, plt)
    _plot_local_and_system_bottlenecks(config, study.aggregate_rows, figures_dir, plt)
    _plot_zone_completion_profiles(config, study, figures_dir, plt)
    _plot_hotspot_width(config, study.aggregate_rows, figures_dir, plt)
    _plot_research_story_panel(config, study, figures_dir, plt)
    _plot_active_zone_concentration(config, study.aggregate_rows, figures_dir, plt)
    _plot_fixed_zone_activity_timeline(config, study, figures_dir, plt)


def _run_specs(config: StaticBaselineStudyConfig) -> list[tuple[str, float, int]]:
    specs = [
        ("skew_sweep", fraction, config.primary_hotspot_width)
        for fraction in sorted(set(config.hot_zone_fractions))
    ]
    for width in sorted(set(config.hotspot_widths)):
        spec = ("width_sensitivity", config.width_sensitivity_hot_fraction, width)
        if width == config.primary_hotspot_width and any(
            math.isclose(config.width_sensitivity_hot_fraction, fraction)
            for fraction in config.hot_zone_fractions
        ):
            continue
        specs.append(spec)
    specs.extend(
        ("active_zone_concentration", 1.0, count)
        for count in sorted(set(config.active_zone_counts))
    )
    return specs


def _panel_config_for_run(
    config: StaticBaselineStudyConfig,
    scenario: str,
    seed: int,
    hot_fraction: float,
    hotspot_width: int,
    request_merge: bool,
    batch_size: int,
) -> PanelStaticZoneConfig:
    merge_label = "merge" if request_merge else "no_merge"
    run_output = (
        config.output_dir
        / "runs"
        / f"{scenario}_hot_{hot_fraction:.3f}_width_{hotspot_width:02d}_{merge_label}_seed_{seed}"
    )
    return PanelStaticZoneConfig(
        output_dir=run_output,
        seed=seed,
        geometry=config.geometry,
        movement=config.movement,
        timing=config.timing,
        workload=PanelWorkloadConfig(
            batch_size=batch_size,
            request_size_bytes=config.workload.request_size_bytes,
            placement="spatial_skew",
            request_merge=request_merge,
            hot_zone=config.workload.hot_zone,
            hot_zone_fraction=hot_fraction,
            hot_zone_width=hotspot_width,
        ),
    )


def _build_run_row(
    scenario: str,
    seed: int,
    hot_fraction: float,
    hotspot_width: int,
    request_merge: bool,
    result: PanelStaticZoneResult,
) -> dict[str, Any]:
    summary = result.summary
    zone_logical = [int(row["logical_request_count"]) for row in result.zone_rows]
    zone_services = [int(row["glass_service_count"]) for row in result.zone_rows]
    zone_completion = [float(row["completion_s"]) for row in result.zone_rows]
    hot_zone = int(summary["config"]["workload"]["hot_zone"])
    hot_zones = {(hot_zone + offset) % int(summary["zone_count"]) for offset in range(hotspot_width)}
    movement_avg = summary["aggregate_component_avg_s"]["shuttle_movement_s"]
    fixed_avg = summary["aggregate_component_avg_s"]["fixed_mechanical_s"]
    reader_avg = summary["aggregate_component_avg_s"]["reader_data_transfer_s"]
    return {
        "scenario": scenario,
        "seed": seed,
        "request_merge": request_merge,
        "hot_zone_fraction_target": hot_fraction,
        "hotspot_width": hotspot_width,
        "hot_zone_fraction_actual": sum(zone_logical[zone] for zone in hot_zones) / sum(zone_logical),
        "request_count": summary["request_count"],
        "service_operation_count": summary["service_operation_count"],
        "requests_per_service": summary["requests_per_service"],
        "productive_cycle_s": summary["productive_cycle_s"],
        "drive_makespan_s": summary["drive_makespan_s"],
        "system_drain_s": summary["system_drain_s"],
        "throughput_req_per_s": summary["throughput_req_per_s"],
        "throughput_service_ops_per_s": summary["throughput_service_ops_per_s"],
        "throughput_mib_per_s": summary["throughput_mib_per_s"],
        "latency_p50_s": summary["latency_p50_s"],
        "latency_p95_s": summary["latency_p95_s"],
        "latency_p99_s": summary["latency_p99_s"],
        "static_capacity_efficiency": summary["static_capacity_efficiency"],
        "stranded_capacity_share": summary["stranded_capacity_share"],
        "ownership_slowdown_vs_ideal": summary["ownership_slowdown_vs_ideal"],
        "ideal_balanced_cycle_lower_bound_s": summary["ideal_balanced_cycle_lower_bound_s"],
        "shuttle_utilization_avg": summary["shuttle_utilization_avg"],
        "shuttle_utilization_max": summary["shuttle_utilization_max"],
        "shuttle_utilization_min": summary["shuttle_utilization_min"],
        "shuttle_utilization_std": summary["shuttle_utilization_std"],
        "reader_utilization_avg": summary["reader_utilization_avg"],
        "reader_utilization_max": summary["reader_utilization_max"],
        "reader_utilization_min": summary["reader_utilization_min"],
        "reader_utilization_std": summary["reader_utilization_std"],
        "zone_logical_request_max_mean_ratio": _max_mean_ratio(zone_logical),
        "zone_service_max_mean_ratio": _max_mean_ratio(zone_services),
        "zone_completion_max_mean_ratio": _max_mean_ratio(zone_completion),
        "hot_region_logical_request_share": sum(zone_logical[zone] for zone in hot_zones) / sum(zone_logical),
        "hot_region_service_share": sum(zone_services[zone] for zone in hot_zones) / sum(zone_services),
        "movement_avg_s_per_service": movement_avg,
        "fixed_mechanical_avg_s_per_service": fixed_avg,
        "reader_avg_s_per_service": reader_avg,
        "movement_active_share": summary["aggregate_component_active_shares"]["shuttle_movement_s"],
        "fixed_mechanical_active_share": summary["aggregate_component_active_shares"]["fixed_mechanical_s"],
        "reader_active_share": summary["aggregate_component_active_shares"]["reader_data_transfer_s"],
        "horizontal_movement_share": summary["movement_component_shares"]["horizontal_movement_s"],
        "vertical_movement_share": summary["movement_component_shares"]["vertical_movement_s"],
        "horizontal_distance_m": summary["horizontal_distance_m"],
        "vertical_levels_traversed": summary["vertical_levels_traversed"],
    }


def _annotate_zone_rows(run: StaticBaselineStudyRun) -> list[dict[str, Any]]:
    return [
        {
            "scenario": run.scenario,
            "seed": run.seed,
            "request_merge": run.request_merge,
            "hot_zone_fraction_target": run.hot_zone_fraction,
            "hotspot_width": run.hotspot_width,
            **row,
        }
        for row in run.result.zone_rows
    ]


def _aggregate_runs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            row["scenario"],
            row["request_merge"],
            row["hot_zone_fraction_target"],
            row["hotspot_width"],
        )
        groups.setdefault(key, []).append(row)
    identity = {
        "scenario",
        "seed",
        "request_merge",
        "hot_zone_fraction_target",
        "hotspot_width",
    }
    aggregate_rows: list[dict[str, Any]] = []
    for key, group in sorted(groups.items(), key=lambda item: item[0]):
        aggregate: dict[str, Any] = {
            "scenario": key[0],
            "request_merge": key[1],
            "hot_zone_fraction_target": key[2],
            "hotspot_width": key[3],
            "run_count": len(group),
        }
        for field in group[0]:
            if field in identity:
                continue
            values = [float(row[field]) for row in group]
            aggregate[f"{field}_mean"] = mean(values)
            aggregate[f"{field}_std"] = pstdev(values) if len(values) > 1 else 0.0
        aggregate_rows.append(aggregate)
    return aggregate_rows


def _build_findings(
    config: StaticBaselineStudyConfig,
    study: StaticBaselineStudyResult,
) -> dict[str, Any]:
    uniform_fraction = min(config.hot_zone_fractions)
    heavy_fraction = max(config.hot_zone_fractions)
    findings: dict[str, Any] = {}
    for request_merge in config.merge_modes:
        label = "merge" if request_merge else "no_merge"
        uniform = _find_aggregate(
            study.aggregate_rows,
            scenario="skew_sweep",
            request_merge=request_merge,
            hot_fraction=uniform_fraction,
            hotspot_width=config.primary_hotspot_width,
        )
        heavy = _find_aggregate(
            study.aggregate_rows,
            scenario="skew_sweep",
            request_merge=request_merge,
            hot_fraction=heavy_fraction,
            hotspot_width=config.primary_hotspot_width,
        )
        findings[label] = {
            "uniform_hot_fraction": uniform_fraction,
            "heavy_hot_fraction": heavy_fraction,
            "uniform_makespan_h": uniform["drive_makespan_s_mean"] / 3600.0,
            "heavy_makespan_h": heavy["drive_makespan_s_mean"] / 3600.0,
            "makespan_increase_ratio": heavy["drive_makespan_s_mean"] / uniform["drive_makespan_s_mean"],
            "throughput_change_ratio": heavy["throughput_req_per_s_mean"] / uniform["throughput_req_per_s_mean"],
            "uniform_capacity_efficiency": uniform["static_capacity_efficiency_mean"],
            "heavy_capacity_efficiency": heavy["static_capacity_efficiency_mean"],
            "uniform_stranded_share": uniform["stranded_capacity_share_mean"],
            "heavy_stranded_share": heavy["stranded_capacity_share_mean"],
            "heavy_ownership_slowdown_vs_ideal": heavy["ownership_slowdown_vs_ideal_mean"],
            "uniform_services": uniform["service_operation_count_mean"],
            "heavy_services": heavy["service_operation_count_mean"],
            "movement_share": heavy["movement_active_share_mean"],
            "fixed_mechanical_share": heavy["fixed_mechanical_active_share_mean"],
            "reader_share": heavy["reader_active_share_mean"],
        }
    concentration = sorted(
        (
            row
            for row in study.aggregate_rows
            if row["scenario"] == "active_zone_concentration" and row["request_merge"]
        ),
        key=lambda row: row["hotspot_width"],
    )
    productive_work = [row["productive_cycle_s_mean"] for row in concentration]
    findings["active_zone_concentration"] = {
        "task_count": config.active_task_count,
        "cases": [
            {
                "active_zone_count": int(row["hotspot_width"]),
                "service_operation_count": row["service_operation_count_mean"],
                "productive_cycle_h": row["productive_cycle_s_mean"] / 3600.0,
                "makespan_h": row["drive_makespan_s_mean"] / 3600.0,
                "capacity_efficiency": row["static_capacity_efficiency_mean"],
                "stranded_capacity_share": row["stranded_capacity_share_mean"],
            }
            for row in concentration
        ],
        "productive_work_range_ratio": (
            (max(productive_work) - min(productive_work)) / mean(productive_work)
            if productive_work and mean(productive_work) > 0
            else 0.0
        ),
    }
    return findings


def _write_analysis(
    path: Path,
    config: StaticBaselineStudyConfig,
    study: StaticBaselineStudyResult,
    findings: dict[str, Any],
) -> None:
    operational = findings["merge"]
    concentration = findings["active_zone_concentration"]
    concentrated = concentration["cases"][0]
    distributed = concentration["cases"][-1]
    lines = [
        "# Static-Zone Baseline Bottleneck Analysis",
        "",
        "## Research purpose",
        "",
        "This study characterizes the strict static-zone baseline before introducing any adaptive policy. "
        "It asks two separate questions: what makes one glass service expensive, and what prevents the full panel from using its aggregate resources under spatial skew?",
        "",
        "## Controlled setup",
        "",
        f"- Layout: {config.geometry.levels // config.geometry.zone_height_racks} rows x 2 sides, "
        f"{config.geometry.levels // config.geometry.zone_height_racks * 2} static zones.",
        "- Each zone owns one shuttle and one local reader.",
        "- A shuttle remains reserved for direct fetch, read, unload, and return; there is no feeder buffer.",
        f"- Batch: {config.workload.batch_size:,} logical requests, "
        f"{config.workload.request_size_bytes / MIB:.0f} MiB/request.",
        f"- Seeds: {', '.join(str(seed) for seed in config.seeds)}.",
        "- Local level/slot coordinates are paired across skew cases; only zone assignment changes.",
        "- Request merge is the default behavior: all requests to the same physical glass are coalesced before scheduling.",
        "- Every compared skew case is evaluated from its resulting merged glass-task set.",
        "",
        "## Observation 1: fixed-zone concentration controls usable parallelism",
        "",
        f"A separate paired experiment starts from the same {concentration['task_count']:,} unique active glass tasks in every case. "
        "The task sizes and local level/slot coordinates are unchanged; only the number of fixed zones that own those tasks changes.",
        "",
        f"Concentrating the tasks in {concentrated['active_zone_count']} fixed zone yields a mean makespan of "
        f"{concentrated['makespan_h']:.2f} h and uses {concentrated['capacity_efficiency'] * 100:.1f}% of panel zone-time capacity. "
        f"Distributing the same task templates across {distributed['active_zone_count']} zones changes these values to "
        f"{distributed['makespan_h']:.2f} h and {distributed['capacity_efficiency'] * 100:.1f}%.",
        "",
        f"The total productive-cycle work varies by only {concentration['productive_work_range_ratio'] * 100:.1f}% across the concentration sweep. "
        "The experiment therefore isolates how many fixed owners can serve the active set, rather than changing logical popularity or merge opportunities.",
        "",
        "> The structural issue is fixed-zone ownership: when active work belongs to only a subset of zones, the remaining resources cannot contribute under strict operation.",
        "",
        "## Observation 2: merge defines the physical workload",
        "",
        f"The balanced and heavy-skew batches both contain {config.workload.batch_size:,} logical requests, but after default merge they contain approximately "
        f"{operational['uniform_services']:.0f} and {operational['heavy_services']:.0f} physical glass services, respectively. "
        "Repeated accesses in the finite hot working set share a single fetch, while the merged bytes are still read by the reader.",
        "",
        "The scheduler should therefore reason about merged glass tasks, not raw request count. Merge is part of the workload semantics, not an alternative policy.",
        "",
        "## Observation 3: static partitioning works when merged demand is balanced",
        "",
        f"At the balanced endpoint, mean makespan is {operational['uniform_makespan_h']:.2f} h and "
        f"the panel converts {operational['uniform_capacity_efficiency'] * 100:.1f}% of its zone-time capacity into active service cycles.",
        "",
        "This is the favorable case for static zones: each shuttle-reader pair receives a comparable merged glass-task queue, so isolation gives predictable motion without stranding much capacity.",
        "",
        "## Observation 4: one merged glass service remains robotics-heavy",
        "",
        f"Under heavy skew, the average active cycle consists of "
        f"{operational['movement_share'] * 100:.1f}% shuttle movement, "
        f"{operational['fixed_mechanical_share'] * 100:.1f}% fixed pick/load/unload/place operations, and "
        f"{operational['reader_share'] * 100:.1f}% reader transfer.",
        "",
        "Movement plus fixed handling still accounts for most of a glass service. Reader share rises when more logical requests merge into each hot glass, but a faster reader alone cannot remove the ownership imbalance between zones.",
        "",
        "## Observation 5: spatial concentration strands otherwise usable resources",
        "",
        f"When the hot region receives {operational['heavy_hot_fraction'] * 100:.1f}% of logical requests, "
        f"mean makespan grows from {operational['uniform_makespan_h']:.2f} h to "
        f"{operational['heavy_makespan_h']:.2f} h ({operational['makespan_increase_ratio']:.2f}x).",
        f"Logical throughput falls to {operational['throughput_change_ratio'] * 100:.1f}% of the balanced case, "
        f"and {operational['heavy_stranded_share'] * 100:.1f}% of total zone-time capacity is idle while hot work remains.",
        f"The static makespan is {operational['heavy_ownership_slowdown_vs_ideal']:.2f}x the work-conserving lower bound computed from the same merged active-cycle work.",
        "",
        "This is especially important because the heavy-skew batch contains fewer physical glass services than the balanced batch, yet still finishes later. The limiting factor is where the merged tasks are owned, not simply how many tasks exist globally.",
        "",
            "## Bottleneck hierarchy",
            "",
            "1. Per glass service: shuttle movement and fixed mechanical operations dominate reader transfer.",
            "2. Balanced system: static zones use aggregate capacity efficiently; local mechanical cost determines throughput.",
            "3. Skewed system: hot-zone serialization and stranded cold-zone capacity dominate the makespan.",
            "4. Reader-bound limit: if reader service is made sufficiently slow, scheduling flexibility will no longer improve aggregate throughput.",
            "",
            "## Transition to the research problem",
            "",
            "The static baseline partitions the complete physical capacity before it observes which platters are active. "
            "The experiment shows that this is harmless when demand is balanced, but it ties batch completion to the busiest owner when the active working set is spatially skewed.",
            "",
            "> The next research question is not simply how to make shuttles faster. It is whether the scheduler can partition the active glass tasks, rather than the full storage space, so that hot work can use otherwise idle shuttle-reader pairs without giving up spatial locality and predictable traffic.",
            "",
            "## Figure guide",
            "",
            "- `fig1_static_performance_vs_skew`: batch-level performance degradation as hot share increases.",
            "- `fig2_ownership_imbalance`: static efficiency and distance from the work-conserving lower bound.",
            "- `fig3_stranded_capacity`: productive versus stranded zone-time capacity.",
            "- `fig4_local_vs_system_bottleneck`: separates per-service cost from system-level ownership loss.",
            "- `fig5_zone_completion_profiles`: shows balanced versus hot-zone completion directly.",
            "- `fig6_hotspot_width_sensitivity`: shows whether the same hot demand is concentrated in one or several zones.",
            "- `fig7_research_story_panel`: condensed paper-ready motivation panel.",
            "- `fig8_active_zone_concentration`: paired active tasks concentrated in 1, 2, 4, or 8 fixed zones.",
            "- `fig9_fixed_zone_activity_timeline`: productive and stranded intervals for each fixed owner.",
            "",
            "## Evidence boundaries",
            "",
            "- Shared-pool, work-stealing, and proposed virtual-zone policies are intentionally not included here.",
            "- Collision is absent because strict zones contain one shuttle each and do not cross boundaries.",
            "- The direct serial cycle does not model feeder prefetch or shuttle-reader pipelining.",
            "- The workload is synthetic and paired; trace-driven temporal validation remains future work.",
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_representative_outputs(
    config: StaticBaselineStudyConfig,
    study: StaticBaselineStudyResult,
) -> None:
    first_seed = config.seeds[0]
    fractions = [min(config.hot_zone_fractions), max(config.hot_zone_fractions)]
    for run in study.runs:
        if run.scenario != "skew_sweep" or run.seed != first_seed:
            continue
        if run.hotspot_width != config.primary_hotspot_width:
            continue
        if not run.request_merge:
            continue
        if not any(math.isclose(run.hot_zone_fraction, fraction) for fraction in fractions):
            continue
        skew_label = "balanced" if math.isclose(run.hot_zone_fraction, fractions[0]) else "heavy_skew"
        output_dir = config.output_dir / "representative" / skew_label
        representative_config = replace(run.panel_config, output_dir=output_dir)
        write_panel_static_zone_outputs(representative_config, run.result)


def _plot_performance_vs_skew(config, rows, output_dir, plt) -> None:
    selected = _select(rows, scenario="skew_sweep", width=config.primary_hotspot_width)
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.5))
    for merge, color, marker, label in _series_styles():
        series = sorted((row for row in selected if row["request_merge"] == merge), key=lambda row: row["hot_zone_fraction_target"])
        x = [row["hot_zone_fraction_target"] * 100 for row in series]
        _line_with_band(axes[0], x, [row["drive_makespan_s_mean"] / 3600 for row in series], [row["drive_makespan_s_std"] / 3600 for row in series], color, marker, label)
        _line_with_band(axes[1], x, [row["throughput_req_per_s_mean"] for row in series], [row["throughput_req_per_s_std"] for row in series], color, marker, label)
    axes[0].set_ylabel("Batch makespan (h)")
    axes[1].set_ylabel("Logical throughput (req/s)")
    for ax in axes:
        ax.set_xlabel("Requests assigned to hot region (%)")
        _style(ax)
    axes[0].set_title("Fixed ownership stretches the critical zone")
    axes[1].set_title("Aggregate throughput falls under skew")
    axes[0].legend(frameon=False, loc="upper left")
    _save(fig, output_dir, "fig1_static_performance_vs_skew")


def _plot_ownership_imbalance(config, rows, output_dir, plt) -> None:
    selected = _select(rows, scenario="skew_sweep", width=config.primary_hotspot_width)
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.5))
    for merge, color, marker, label in _series_styles():
        series = sorted((row for row in selected if row["request_merge"] == merge), key=lambda row: row["hot_zone_fraction_target"])
        x = [row["hot_zone_fraction_target"] * 100 for row in series]
        axes[0].plot(x, [row["static_capacity_efficiency_mean"] * 100 for row in series], color=color, marker=marker, linewidth=2, label=label)
        axes[1].plot(x, [row["ownership_slowdown_vs_ideal_mean"] for row in series], color=color, marker=marker, linewidth=2, label=label)
    axes[0].axhline(100, color="#6B7280", linewidth=1, linestyle=":", zorder=1)
    axes[1].axhline(1, color="#6B7280", linewidth=1, linestyle=":", zorder=1)
    axes[0].set_ylabel("Static capacity efficiency (%)")
    axes[1].set_ylabel("Makespan / balanced-work lower bound")
    for ax in axes:
        ax.set_xlabel("Requests assigned to hot region (%)")
        _style(ax)
    axes[0].set_title("Cold-zone capacity becomes stranded")
    axes[1].set_title("Ownership, not total work, sets makespan")
    axes[0].legend(frameon=False, loc="lower left")
    _save(fig, output_dir, "fig2_ownership_imbalance")


def _plot_stranded_capacity(config, rows, output_dir, plt) -> None:
    series = sorted(
        (row for row in _select(rows, scenario="skew_sweep", width=config.primary_hotspot_width) if row["request_merge"]),
        key=lambda row: row["hot_zone_fraction_target"],
    )
    x = [row["hot_zone_fraction_target"] * 100 for row in series]
    productive = [row["static_capacity_efficiency_mean"] * 100 for row in series]
    stranded = [row["stranded_capacity_share_mean"] * 100 for row in series]
    fig, ax = plt.subplots(figsize=(7.1, 3.8))
    ax.bar(x, productive, width=8, color="#2F6B9A", label="Active service cycles")
    ax.bar(x, stranded, width=8, bottom=productive, color="#D7DEE8", label="Stranded zone capacity")
    for xpos, active in zip(x, productive):
        ax.text(xpos, active / 2, f"{active:.0f}%", ha="center", va="center", color="white", fontsize=9)
    ax.set_xlabel("Requests assigned to hot region (%)")
    ax.set_ylabel("Available zone-time capacity (%)")
    ax.set_ylim(0, 103)
    ax.set_title("Spatial skew leaves resources idle while hot work remains")
    ax.legend(frameon=False, loc="lower left")
    _style(ax)
    _save(fig, output_dir, "fig3_stranded_capacity")


def _plot_local_and_system_bottlenecks(config, rows, output_dir, plt) -> None:
    selected = _select(rows, scenario="skew_sweep", width=config.primary_hotspot_width)
    uniform_fraction = min(config.hot_zone_fractions)
    heavy_fraction = max(config.hot_zone_fractions)
    uniform = _find_aggregate(selected, "skew_sweep", True, uniform_fraction, config.primary_hotspot_width)
    heavy = _find_aggregate(selected, "skew_sweep", True, heavy_fraction, config.primary_hotspot_width)
    labels = ["Balanced", "Heavy skew"]
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.6))
    movement = [uniform["movement_active_share_mean"] * 100, heavy["movement_active_share_mean"] * 100]
    fixed = [uniform["fixed_mechanical_active_share_mean"] * 100, heavy["fixed_mechanical_active_share_mean"] * 100]
    reader = [uniform["reader_active_share_mean"] * 100, heavy["reader_active_share_mean"] * 100]
    axes[0].bar(labels, movement, color="#2F6B9A", label="Movement")
    axes[0].bar(labels, fixed, bottom=movement, color="#4C9F70", label="Fixed mechanics")
    axes[0].bar(labels, reader, bottom=[a + b for a, b in zip(movement, fixed)], color="#7A5EA8", label="Reader transfer")
    productive = [uniform["static_capacity_efficiency_mean"] * 100, heavy["static_capacity_efficiency_mean"] * 100]
    stranded = [100 - value for value in productive]
    axes[1].bar(labels, productive, color="#2F6B9A", label="Productive")
    axes[1].bar(labels, stranded, bottom=productive, color="#D7DEE8", label="Stranded")
    axes[0].set_ylabel("Per-service active cycle (%)")
    axes[1].set_ylabel("Panel zone-time capacity (%)")
    axes[0].set_title("Local bottleneck: robotics")
    axes[1].set_title("System bottleneck: fixed ownership")
    for ax in axes:
        ax.set_ylim(0, 103)
        _style(ax)
        ax.legend(frameon=False, loc="lower left")
    _save(fig, output_dir, "fig4_local_vs_system_bottleneck")


def _plot_zone_completion_profiles(config, study, output_dir, plt) -> None:
    first_seed = config.seeds[0]
    fractions = [min(config.hot_zone_fractions), max(config.hot_zone_fractions)]
    runs = [
        next(
            run
            for run in study.runs
            if run.scenario == "skew_sweep"
            and run.seed == first_seed
            and run.request_merge
            and run.hotspot_width == config.primary_hotspot_width
            and math.isclose(run.hot_zone_fraction, fraction)
        )
        for fraction in fractions
    ]
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 3.6), sharey=True)
    for ax, run, title in zip(axes, runs, ["Balanced demand", "80% hot-region demand"]):
        zone_ids = [row["zone_id"] for row in run.result.zone_rows]
        completion = [row["completion_h"] for row in run.result.zone_rows]
        requests = [row["logical_request_count"] / run.result.summary["request_count"] * 100 for row in run.result.zone_rows]
        colors = ["#C84C4C" if zone_id == config.workload.hot_zone and title.startswith("80") else "#2F6B9A" for zone_id in zone_ids]
        ax.bar(zone_ids, completion, color=colors)
        ax.set_xlabel("Static zone")
        ax.set_title(title)
        twin = ax.twinx()
        twin.plot(zone_ids, requests, color="#D9822B", marker="o", linewidth=1.5, label="Request share")
        twin.set_ylabel("Logical request share (%)", color="#D9822B")
        twin.tick_params(axis="y", colors="#D9822B")
        twin.spines["top"].set_visible(False)
        twin.spines["right"].set_color("#D9822B")
        _style(ax)
    axes[0].set_ylabel("Zone completion time (h)")
    _save(fig, output_dir, "fig5_zone_completion_profiles")


def _plot_hotspot_width(config, rows, output_dir, plt) -> None:
    selected = [
        row
        for row in rows
        if math.isclose(row["hot_zone_fraction_target"], config.width_sensitivity_hot_fraction)
        and (
            row["scenario"] == "width_sensitivity"
            or (row["scenario"] == "skew_sweep" and row["hotspot_width"] == config.primary_hotspot_width)
        )
    ]
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.5))
    for merge, color, marker, label in _series_styles():
        series = sorted((row for row in selected if row["request_merge"] == merge), key=lambda row: row["hotspot_width"])
        axes[0].plot([row["hotspot_width"] for row in series], [row["drive_makespan_s_mean"] / 3600 for row in series], color=color, marker=marker, linewidth=2, label=label)
        axes[1].plot([row["hotspot_width"] for row in series], [row["static_capacity_efficiency_mean"] * 100 for row in series], color=color, marker=marker, linewidth=2, label=label)
    axes[0].set_ylabel("Batch makespan (h)")
    axes[1].set_ylabel("Static capacity efficiency (%)")
    for ax in axes:
        ax.set_xlabel("Zones covered by the hot region")
        ax.set_xticks(sorted(set(config.hotspot_widths)))
        _style(ax)
    axes[0].set_title("A wider hotspot can use more fixed owners")
    axes[1].set_title("Concentration determines resource stranding")
    axes[0].legend(frameon=False, loc="upper right")
    _save(fig, output_dir, "fig6_hotspot_width_sensitivity")


def _plot_research_story_panel(config, study, output_dir, plt) -> None:
    rows = study.aggregate_rows
    selected = _select(rows, scenario="skew_sweep", width=config.primary_hotspot_width)
    merged = sorted((row for row in selected if row["request_merge"]), key=lambda row: row["hot_zone_fraction_target"])
    x = [row["hot_zone_fraction_target"] * 100 for row in merged]
    fig, axes = plt.subplots(2, 2, figsize=(9.5, 7.0))
    axes[0, 0].plot(x, [row["drive_makespan_s_mean"] / 3600 for row in merged], color="#2F6B9A", marker="o", linewidth=2)
    axes[0, 0].set_ylabel("Batch makespan (h)")
    axes[0, 0].set_title("A. Static makespan follows hot demand")
    axes[0, 1].plot(x, [row["static_capacity_efficiency_mean"] * 100 for row in merged], color="#4C9F70", marker="s", linewidth=2)
    axes[0, 1].set_ylabel("Capacity efficiency (%)")
    axes[0, 1].set_title("B. Cold resources become stranded")
    productive = [merged[0]["static_capacity_efficiency_mean"] * 100, merged[-1]["static_capacity_efficiency_mean"] * 100]
    axes[1, 0].bar(["Balanced", "Heavy skew"], productive, color="#2F6B9A", label="Productive")
    axes[1, 0].bar(["Balanced", "Heavy skew"], [100 - value for value in productive], bottom=productive, color="#D7DEE8", label="Stranded")
    axes[1, 0].set_ylabel("Panel zone-time capacity (%)")
    axes[1, 0].set_title("C. Same hardware, different usable capacity")
    axes[1, 0].legend(frameon=False, loc="lower left")
    uniform = merged[0]
    heavy = merged[-1]
    components = [
        [uniform["movement_active_share_mean"] * 100, heavy["movement_active_share_mean"] * 100],
        [uniform["fixed_mechanical_active_share_mean"] * 100, heavy["fixed_mechanical_active_share_mean"] * 100],
        [uniform["reader_active_share_mean"] * 100, heavy["reader_active_share_mean"] * 100],
    ]
    bottoms = [0.0, 0.0]
    for values, color, label in zip(components, ["#2F6B9A", "#4C9F70", "#7A5EA8"], ["Movement", "Fixed mechanics", "Reader"]):
        axes[1, 1].bar(["Balanced", "Heavy skew"], values, bottom=bottoms, color=color, label=label)
        bottoms = [bottom + value for bottom, value in zip(bottoms, values)]
    axes[1, 1].set_ylabel("Per-service active cycle (%)")
    axes[1, 1].set_title("D. Local cost stays mechanical")
    axes[1, 1].legend(frameon=False, loc="lower left")
    for ax in axes.flat:
        if ax in (axes[0, 0], axes[0, 1]):
            ax.set_xlabel("Requests assigned to hot region (%)")
        _style(ax)
    fig.suptitle("Why static physical ownership fails under spatially skewed active workloads", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    _save(fig, output_dir, "fig7_research_story_panel", tight=False)


def _plot_active_zone_concentration(config, rows, output_dir, plt) -> None:
    series = sorted(
        (
            row
            for row in rows
            if row["scenario"] == "active_zone_concentration" and row["request_merge"]
        ),
        key=lambda row: row["hotspot_width"],
    )
    active_zones = [int(row["hotspot_width"]) for row in series]
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 3.7))
    axes[0].plot(
        active_zones,
        [row["drive_makespan_s_mean"] / 3600.0 for row in series],
        color="#C84C4C",
        marker="o",
        linewidth=2,
        label="Strict fixed zones",
    )
    axes[0].plot(
        active_zones,
        [row["ideal_balanced_cycle_lower_bound_s_mean"] / 3600.0 for row in series],
        color="#6B7280",
        marker="s",
        linewidth=1.5,
        linestyle="--",
        label="Work-conserving lower bound",
    )
    productive = [row["static_capacity_efficiency_mean"] * 100 for row in series]
    stranded = [row["stranded_capacity_share_mean"] * 100 for row in series]
    axes[1].bar(active_zones, productive, color="#2F6B9A", label="Productive")
    axes[1].bar(active_zones, stranded, bottom=productive, color="#D7DEE8", label="Stranded")
    axes[0].set_ylabel("Batch makespan (h)")
    axes[1].set_ylabel("Panel zone-time capacity (%)")
    axes[0].set_title("Same active tasks, different fixed-zone parallelism")
    axes[1].set_title("Inactive owners strand available capacity")
    for ax in axes:
        ax.set_xlabel("Fixed zones containing active tasks")
        ax.set_xticks(active_zones)
        _style(ax)
        ax.legend(frameon=False)
    axes[1].set_ylim(0, 103)
    _save(fig, output_dir, "fig8_active_zone_concentration")


def _plot_fixed_zone_activity_timeline(config, study, output_dir, plt) -> None:
    first_seed = config.seeds[0]
    runs = sorted(
        (
            run
            for run in study.runs
            if run.scenario == "active_zone_concentration"
            and run.seed == first_seed
            and run.request_merge
        ),
        key=lambda run: run.hotspot_width,
    )
    fig, axes = plt.subplots(2, 2, figsize=(9.5, 6.8), sharey=True)
    for ax, run in zip(axes.flat, runs):
        zone_rows = sorted(run.result.zone_rows, key=lambda row: int(row["zone_id"]))
        zone_ids = [int(row["zone_id"]) for row in zone_rows]
        productive = [float(row["active_cycle_h"]) for row in zone_rows]
        drain_h = float(run.result.summary["system_drain_s"]) / 3600.0
        stranded = [max(0.0, drain_h - value) for value in productive]
        ax.barh(zone_ids, productive, color="#2F6B9A", label="Productive interval")
        ax.barh(zone_ids, stranded, left=productive, color="#D7DEE8", label="Idle while panel drains")
        ax.set_title(f"Active work owned by {run.hotspot_width} fixed zone(s)")
        ax.set_xlabel("Time from batch start (h)")
        ax.set_yticks(zone_ids)
        ax.invert_yaxis()
        ax.grid(True, axis="x", color="#D7DEE8", linewidth=0.7, zorder=0)
        ax.grid(False, axis="y")
        for spine in ["top", "right"]:
            ax.spines[spine].set_visible(False)
    axes[0, 0].set_ylabel("Fixed zone")
    axes[1, 0].set_ylabel("Fixed zone")
    axes[0, 0].legend(frameon=False, loc="lower right")
    fig.suptitle("Fixed ownership leaves non-owning resources idle", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    _save(fig, output_dir, "fig9_fixed_zone_activity_timeline", tight=False)


def _series_styles():
    return [
        (True, "#2F6B9A", "o", "Merged glass workload"),
    ]


def _line_with_band(ax, x, y, std, color, marker, label) -> None:
    ax.plot(x, y, color=color, marker=marker, linewidth=2, label=label, zorder=3)
    lower = [max(0.0, value - spread) for value, spread in zip(y, std)]
    upper = [value + spread for value, spread in zip(y, std)]
    ax.fill_between(x, lower, upper, color=color, alpha=0.12, linewidth=0, zorder=2)


def _select(rows, scenario: str, width: int):
    return [row for row in rows if row["scenario"] == scenario and row["hotspot_width"] == width]


def _find_aggregate(rows, scenario, request_merge, hot_fraction, hotspot_width):
    return next(
        row
        for row in rows
        if row["scenario"] == scenario
        and row["request_merge"] == request_merge
        and math.isclose(row["hot_zone_fraction_target"], hot_fraction)
        and row["hotspot_width"] == hotspot_width
    )


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
    fig.savefig(output_dir / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(output_dir / f"{name}.png", dpi=300, bbox_inches="tight")
    import matplotlib.pyplot as plt

    plt.close(fig)


def _distribute_exact(total: int, zones: list[int], counts: dict[int, int]) -> None:
    if total <= 0 or not zones:
        return
    quotient, remainder = divmod(total, len(zones))
    for index, zone_id in enumerate(zones):
        counts[zone_id] += quotient + (1 if index < remainder else 0)


def _max_mean_ratio(values) -> float:
    return max(values, default=0.0) / mean(values) if values and mean(values) > 0 else 0.0


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _resolve_path(value: str, base_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()
