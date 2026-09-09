from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import json
import math
import os
from pathlib import Path
import random
from statistics import mean, pstdev
from typing import Any

from .panel_static_zone import (
    MIB,
    PanelGeometryConfig,
    PanelMovementConfig,
    PanelRequest,
    PanelStaticZoneConfig,
    PanelStaticZoneSimulator,
    PanelTimingConfig,
    PanelWorkloadConfig,
)
from .paths import portable_path, repository_root_for_config


GROWING_FOOTPRINT = "growing_footprint"
FIXED_FOOTPRINT = "fixed_footprint_control"


@dataclass(frozen=True)
class CapacityGeometryConfig:
    levels: int
    zone_height_racks: int
    rack_length_m: float
    slots_per_half_per_rack: int
    fixed_footprint_half_length_m: float
    glass_capacity_bytes: int

    def validate(self) -> None:
        if self.levels <= 0:
            raise ValueError("geometry.levels must be positive")
        if self.zone_height_racks <= 0:
            raise ValueError("geometry.zone_height_racks must be positive")
        if self.levels % self.zone_height_racks != 0:
            raise ValueError(
                "geometry.levels must be divisible by zone_height_racks"
            )
        if self.rack_length_m <= 0:
            raise ValueError("geometry.rack_length_m must be positive")
        if self.slots_per_half_per_rack <= 1:
            raise ValueError(
                "geometry.slots_per_half_per_rack must exceed one"
            )
        if self.fixed_footprint_half_length_m <= 0:
            raise ValueError(
                "geometry.fixed_footprint_half_length_m must be positive"
            )
        if self.glass_capacity_bytes <= 0:
            raise ValueError("geometry.glass_capacity_bytes must be positive")


@dataclass(frozen=True)
class CapacityWorkloadConfig:
    task_count: int
    request_size_bytes: int

    def validate(self, zone_count: int, minimum_local_capacity: int) -> None:
        if self.task_count <= 0:
            raise ValueError("workload.task_count must be positive")
        if self.task_count % zone_count != 0:
            raise ValueError(
                "workload.task_count must divide evenly across service lanes"
            )
        if self.request_size_bytes <= 0:
            raise ValueError("workload.request_size_bytes must be positive")
        if self.task_count // zone_count > minimum_local_capacity:
            raise ValueError(
                "minimum rack scale cannot hold unique tasks per service lane"
            )


@dataclass(frozen=True)
class CapacityScalabilityConfig:
    output_dir: Path
    seeds: tuple[int, ...]
    storage_rack_counts: tuple[int, ...]
    reader_count: int
    shuttle_count: int
    geometry: CapacityGeometryConfig
    movement: PanelMovementConfig
    timing: PanelTimingConfig
    workload: CapacityWorkloadConfig

    @property
    def zone_count(self) -> int:
        return (
            self.geometry.levels // self.geometry.zone_height_racks
        ) * 2

    def validate(self) -> None:
        self.geometry.validate()
        self.movement.validate()
        self.timing.validate()
        if not self.seeds or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds must be non-empty and unique")
        if (
            not self.storage_rack_counts
            or tuple(sorted(set(self.storage_rack_counts)))
            != self.storage_rack_counts
            or any(value <= 0 for value in self.storage_rack_counts)
        ):
            raise ValueError(
                "storage_rack_counts must be positive, unique, and increasing"
            )
        if self.reader_count != self.zone_count:
            raise ValueError(
                "reader_count must match the fixed service-lane count"
            )
        if self.shuttle_count != self.zone_count:
            raise ValueError(
                "shuttle_count must match the fixed service-lane count"
            )
        minimum_capacity = (
            self.geometry.zone_height_racks
            * self.geometry.slots_per_half_per_rack
            * self.storage_rack_counts[0]
        )
        self.workload.validate(self.zone_count, minimum_capacity)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "output_dir": portable_path(self.output_dir),
            "seeds": list(self.seeds),
            "storage_rack_counts": list(self.storage_rack_counts),
            "reader_count": self.reader_count,
            "shuttle_count": self.shuttle_count,
            "geometry": asdict(self.geometry),
            "movement": asdict(self.movement),
            "timing": asdict(self.timing),
            "workload": asdict(self.workload),
            "experiment_scope": {
                "capacity_only": True,
                "fixed_logical_and_physical_work": True,
                "paired_normalized_locations": True,
                "controller_cpu_cost": False,
                "shuttle_collision": False,
                "request_reordering": False,
                "workload_skew": False,
            },
        }


@dataclass(frozen=True)
class CapacityScalabilityResult:
    run_rows: list[dict[str, Any]]
    aggregate_rows: list[dict[str, Any]]
    validation: dict[str, Any]
    findings: dict[str, Any]


def load_capacity_scalability_config(
    path: str | Path,
) -> CapacityScalabilityConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    base_dir = repository_root_for_config(config_path)
    output_dir = Path(raw["output_dir"]).expanduser()
    if not output_dir.is_absolute():
        output_dir = (base_dir / output_dir).resolve()
    config = CapacityScalabilityConfig(
        output_dir=output_dir,
        seeds=tuple(int(value) for value in raw["seeds"]),
        storage_rack_counts=tuple(
            int(value) for value in raw["storage_rack_counts"]
        ),
        reader_count=int(raw["reader_count"]),
        shuttle_count=int(raw["shuttle_count"]),
        geometry=CapacityGeometryConfig(**raw["geometry"]),
        movement=PanelMovementConfig(**raw["movement"]),
        timing=PanelTimingConfig(**raw["timing"]),
        workload=CapacityWorkloadConfig(**raw["workload"]),
    )
    config.validate()
    return config


def run_capacity_scalability(
    config: CapacityScalabilityConfig,
) -> CapacityScalabilityResult:
    config.validate()
    run_rows: list[dict[str, Any]] = []
    failures: list[str] = []

    for seed in config.seeds:
        templates = _build_task_templates(config, seed)
        expected_signature = _template_signature(templates)
        for scenario in (FIXED_FOOTPRINT, GROWING_FOOTPRINT):
            for rack_count in config.storage_rack_counts:
                panel_config = _panel_config(
                    config,
                    seed,
                    rack_count,
                    scenario,
                )
                simulator = PanelStaticZoneSimulator(panel_config)
                requests = _materialize_tasks(
                    simulator,
                    templates,
                    panel_config.geometry.slots_per_half,
                    config.workload.request_size_bytes,
                )
                _validate_requests(
                    config,
                    requests,
                    expected_signature,
                    templates,
                    seed,
                    rack_count,
                    scenario,
                    failures,
                )
                result = simulator.run(requests)
                summary = result.summary
                platter_slots = (
                    panel_config.geometry.levels
                    * 2
                    * panel_config.geometry.slots_per_half
                )
                movement_avg = summary["aggregate_component_avg_s"][
                    "shuttle_movement_s"
                ]
                active_avg = summary["avg_cycle_s_per_service"]
                service_count = summary["service_operation_count"]
                components = summary["component_totals_s"]
                reader_service_avg = (
                    components["reader_load_s"]
                    + components["read_s"]
                    + components["reader_unload_s"]
                ) / service_count
                reader_read_avg = components["read_s"] / service_count
                reader_load_unload_avg = (
                    components["reader_load_s"]
                    + components["reader_unload_s"]
                ) / service_count
                storage_handling_avg = (
                    components["storage_pick_s"]
                    + components["storage_place_s"]
                ) / service_count
                run_rows.append(
                    {
                        "seed": seed,
                        "scenario": scenario,
                        "storage_rack_count": rack_count,
                        "half_panel_length_m": (
                            panel_config.geometry.half_panel_length_m
                        ),
                        "slots_per_half": (
                            panel_config.geometry.slots_per_half
                        ),
                        "platter_slot_count": platter_slots,
                        "reader_count": summary["reader_count"],
                        "shuttle_count": summary["shuttle_count"],
                        "physical_task_count": summary[
                            "service_operation_count"
                        ],
                        "logical_request_count": summary["request_count"],
                        "total_bytes": (
                            summary["request_count"]
                            * config.workload.request_size_bytes
                        ),
                        "drive_makespan_s": summary["drive_makespan_s"],
                        "system_drain_s": summary["system_drain_s"],
                        "throughput_req_per_s": summary[
                            "throughput_req_per_s"
                        ],
                        "throughput_mib_per_s": summary[
                            "throughput_mib_per_s"
                        ],
                        "latency_p95_s": summary["latency_p95_s"],
                        "latency_p99_s": summary["latency_p99_s"],
                        "avg_cycle_s": active_avg,
                        "avg_shuttle_movement_s": movement_avg,
                        "avg_fixed_mechanical_s": summary[
                            "aggregate_component_avg_s"
                        ]["fixed_mechanical_s"],
                        "avg_reader_transfer_s": summary[
                            "aggregate_component_avg_s"
                        ]["reader_data_transfer_s"],
                        "avg_reader_service_s": reader_service_avg,
                        "avg_reader_read_s": reader_read_avg,
                        "avg_reader_load_unload_s": reader_load_unload_avg,
                        "avg_storage_handling_s": storage_handling_avg,
                        "movement_time_share": (
                            movement_avg / active_avg
                            if active_avg > 0
                            else 0.0
                        ),
                        "reader_service_time_share": (
                            reader_service_avg / active_avg
                            if active_avg > 0
                            else 0.0
                        ),
                        "reader_read_time_share": (
                            reader_read_avg / active_avg
                            if active_avg > 0
                            else 0.0
                        ),
                        "reader_load_unload_time_share": (
                            reader_load_unload_avg / active_avg
                            if active_avg > 0
                            else 0.0
                        ),
                        "storage_handling_time_share": (
                            storage_handling_avg / active_avg
                            if active_avg > 0
                            else 0.0
                        ),
                        "reader_utilization": summary[
                            "reader_utilization_avg"
                        ],
                        "shuttle_utilization": summary[
                            "shuttle_utilization_avg"
                        ],
                        "horizontal_distance_m_per_task": (
                            summary["horizontal_distance_m"]
                            / summary["service_operation_count"]
                        ),
                    }
                )

    _normalize_rows(config, run_rows)
    aggregate_rows = _aggregate(run_rows)
    _validate_results(config, aggregate_rows, failures)
    if failures:
        raise RuntimeError(
            "capacity-scalability validation failed: "
            + "; ".join(failures)
        )
    findings = _build_findings(config, aggregate_rows)
    return CapacityScalabilityResult(
        run_rows=run_rows,
        aggregate_rows=aggregate_rows,
        validation={
            "passed": True,
            "checked_runs": len(run_rows),
            "paired_seeds": len(config.seeds),
            "scenario_count": 2,
            "fixed_readers": config.reader_count,
            "fixed_shuttles": config.shuttle_count,
            "exact_physical_tasks": config.workload.task_count,
            "exact_logical_requests": config.workload.task_count,
            "unique_platter_targets_per_run": True,
            "balanced_tasks_per_service_lane": True,
            "paired_normalized_locations": True,
            "fixed_footprint_control_is_stable": True,
            "growing_footprint_movement_is_monotonic": True,
            "failures": [],
        },
        findings=findings,
    )


def write_capacity_scalability_outputs(
    config: CapacityScalabilityConfig,
    result: CapacityScalabilityResult,
) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    _write_rows(config.output_dir / "run_summary.csv", result.run_rows)
    _write_rows(
        config.output_dir / "aggregate_summary.csv",
        result.aggregate_rows,
    )
    with (config.output_dir / "config.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(config.to_json_dict(), handle, indent=2)
        handle.write("\n")
    with (config.output_dir / "summary.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(
            {
                "config": config.to_json_dict(),
                "run_count": len(result.run_rows),
                "aggregate_count": len(result.aggregate_rows),
                "validation": result.validation,
                "findings": result.findings,
            },
            handle,
            indent=2,
        )
        handle.write("\n")
    _write_report(
        config.output_dir / "CAPACITY_SCALABILITY_ANALYSIS_ZH.md",
        config,
        result,
    )
    figures_dir = config.output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    _write_figures(result, figures_dir)


def _panel_config(
    config: CapacityScalabilityConfig,
    seed: int,
    rack_count: int,
    scenario: str,
) -> PanelStaticZoneConfig:
    slots_per_half = (
        config.geometry.slots_per_half_per_rack * rack_count
    )
    if scenario == GROWING_FOOTPRINT:
        half_panel_length_m = config.geometry.rack_length_m * rack_count
    elif scenario == FIXED_FOOTPRINT:
        half_panel_length_m = (
            config.geometry.fixed_footprint_half_length_m
        )
    else:
        raise ValueError(f"unsupported scenario: {scenario}")
    return PanelStaticZoneConfig(
        output_dir=config.output_dir,
        seed=seed,
        geometry=PanelGeometryConfig(
            levels=config.geometry.levels,
            zone_height_racks=config.geometry.zone_height_racks,
            half_panel_length_m=half_panel_length_m,
            slots_per_half=slots_per_half,
            glass_capacity_bytes=config.geometry.glass_capacity_bytes,
        ),
        movement=config.movement,
        timing=config.timing,
        workload=PanelWorkloadConfig(
            batch_size=config.workload.task_count,
            request_size_bytes=config.workload.request_size_bytes,
            placement="uniform_round_robin",
            request_merge=False,
        ),
    )


def _build_task_templates(
    config: CapacityScalabilityConfig,
    seed: int,
) -> list[tuple[int, int, float]]:
    tasks_per_zone = config.workload.task_count // config.zone_count
    rng = random.Random(seed)
    templates: list[tuple[int, int, float]] = []
    for zone_id in range(config.zone_count):
        ranks = list(range(tasks_per_zone))
        rng.shuffle(ranks)
        for index, rank in enumerate(ranks):
            local_level = rng.randrange(config.geometry.zone_height_racks)
            normalized_reader_distance = (rank + 0.5) / tasks_per_zone
            templates.append(
                (zone_id, local_level, normalized_reader_distance)
            )
    rng.shuffle(templates)
    return templates


def _materialize_tasks(
    simulator: PanelStaticZoneSimulator,
    templates: list[tuple[int, int, float]],
    slots_per_half: int,
    size_bytes: int,
) -> list[PanelRequest]:
    requests = []
    for index, (zone_id, local_level, distance) in enumerate(templates):
        reader_relative_slot = min(
            slots_per_half - 1,
            int(distance * slots_per_half),
        )
        side = simulator.zones[zone_id].side
        slot = (
            reader_relative_slot
            if side == "left"
            else slots_per_half - 1 - reader_relative_slot
        )
        requests.append(
            simulator.make_request(
                request_index=index,
                zone_id=zone_id,
                local_level=local_level,
                slot_in_half=slot,
                size_bytes=size_bytes,
            )
        )
    return requests


def _template_signature(
    templates: list[tuple[int, int, float]],
) -> tuple[tuple[int, int, float], ...]:
    return tuple(
        (zone_id, local_level, round(distance, 12))
        for zone_id, local_level, distance in templates
    )


def _validate_requests(
    config: CapacityScalabilityConfig,
    requests: list[PanelRequest],
    expected_signature: tuple[tuple[int, int, float], ...],
    templates: list[tuple[int, int, float]],
    seed: int,
    rack_count: int,
    scenario: str,
    failures: list[str],
) -> None:
    label = f"seed {seed} {scenario} racks {rack_count}"
    if _template_signature(templates) != expected_signature:
        failures.append(f"{label}: paired task templates changed")
    if len(requests) != config.workload.task_count:
        failures.append(f"{label}: physical task count changed")
    if len({request.platter_id for request in requests}) != len(requests):
        failures.append(f"{label}: platter targets are not unique")
    observed = [
        sum(request.zone_id == zone_id for request in requests)
        for zone_id in range(config.zone_count)
    ]
    expected = config.workload.task_count // config.zone_count
    if any(count != expected for count in observed):
        failures.append(f"{label}: service-lane work is not balanced")
    if sum(request.size_bytes for request in requests) != (
        config.workload.task_count * config.workload.request_size_bytes
    ):
        failures.append(f"{label}: total bytes changed")


def _normalize_rows(
    config: CapacityScalabilityConfig,
    rows: list[dict[str, Any]],
) -> None:
    baseline_racks = config.storage_rack_counts[0]
    baselines = {
        (int(row["seed"]), str(row["scenario"])): float(
            row["throughput_req_per_s"]
        )
        for row in rows
        if int(row["storage_rack_count"]) == baseline_racks
    }
    for row in rows:
        baseline = baselines[(int(row["seed"]), str(row["scenario"]))]
        retained = float(row["throughput_req_per_s"]) / baseline
        row["normalized_throughput"] = retained
        row["throughput_loss"] = 1.0 - retained


def _aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["scenario"]), int(row["storage_rack_count"]))
        groups.setdefault(key, []).append(row)
    identity = {"seed", "scenario", "storage_rack_count"}
    aggregates = []
    for (scenario, rack_count), group in sorted(groups.items()):
        aggregate: dict[str, Any] = {
            "scenario": scenario,
            "storage_rack_count": rack_count,
            "run_count": len(group),
        }
        for field in group[0]:
            if field in identity:
                continue
            values = [float(row[field]) for row in group]
            std = pstdev(values) if len(values) > 1 else 0.0
            aggregate[f"{field}_mean"] = mean(values)
            aggregate[f"{field}_std"] = std
            aggregate[f"{field}_ci95"] = (
                1.96 * std / math.sqrt(len(values))
            )
        aggregates.append(aggregate)
    return aggregates


def _validate_results(
    config: CapacityScalabilityConfig,
    rows: list[dict[str, Any]],
    failures: list[str],
) -> None:
    expected_rows = len(config.storage_rack_counts) * 2
    if len(rows) != expected_rows:
        failures.append("aggregate scenario/rack count changed")
    for row in rows:
        if row["physical_task_count_mean"] != config.workload.task_count:
            failures.append("a sweep point changed physical task count")
        if row["logical_request_count_mean"] != config.workload.task_count:
            failures.append("a sweep point changed logical request count")
        if row["reader_count_mean"] != config.reader_count:
            failures.append("a sweep point changed reader count")
        if row["shuttle_count_mean"] != config.shuttle_count:
            failures.append("a sweep point changed shuttle count")
        decomposed = (
            row["avg_shuttle_movement_s_mean"]
            + row["avg_reader_read_s_mean"]
            + row["avg_reader_load_unload_s_mean"]
            + row["avg_storage_handling_s_mean"]
        )
        if not math.isclose(
            decomposed,
            row["avg_cycle_s_mean"],
            rel_tol=1e-10,
            abs_tol=1e-10,
        ):
            failures.append("time breakdown does not sum to cycle time")

    control = _scenario_rows(rows, FIXED_FOOTPRINT)
    growing = _scenario_rows(rows, GROWING_FOOTPRINT)
    control_retained = [row["normalized_throughput_mean"] for row in control]
    if max(control_retained) - min(control_retained) > 0.02:
        failures.append("fixed-footprint control changed by more than 2%")
    lengths = [row["half_panel_length_m_mean"] for row in growing]
    if any(right <= left for left, right in zip(lengths, lengths[1:])):
        failures.append("growing-footprint length is not increasing")
    movement = [row["avg_shuttle_movement_s_mean"] for row in growing]
    if any(
        right + 1e-9 < left
        for left, right in zip(movement, movement[1:])
    ):
        failures.append("growing-footprint movement is not monotonic")
    throughput = [row["normalized_throughput_mean"] for row in growing]
    if any(
        right > left + 1e-9
        for left, right in zip(throughput, throughput[1:])
    ):
        failures.append("growing-footprint throughput is not monotonic")
    reader_service = [row["avg_reader_service_s_mean"] for row in growing]
    if max(reader_service) - min(reader_service) > 1e-9:
        failures.append("reader service time changed across capacity scales")
    reader_read = [row["avg_reader_read_s_mean"] for row in growing]
    if max(reader_read) - min(reader_read) > 1e-9:
        failures.append("reader read time changed across capacity scales")
    reader_load_unload = [
        row["avg_reader_load_unload_s_mean"] for row in growing
    ]
    if max(reader_load_unload) - min(reader_load_unload) > 1e-9:
        failures.append("reader load/unload time changed across capacity scales")
    storage_handling = [
        row["avg_storage_handling_s_mean"] for row in growing
    ]
    if max(storage_handling) - min(storage_handling) > 1e-9:
        failures.append("storage handling time changed across capacity scales")
    reader_share = [row["reader_service_time_share_mean"] for row in growing]
    if any(
        right > left + 1e-9
        for left, right in zip(reader_share, reader_share[1:])
    ):
        failures.append("reader service share is not monotonic")


def _scenario_rows(
    rows: list[dict[str, Any]],
    scenario: str,
) -> list[dict[str, Any]]:
    return sorted(
        [row for row in rows if row["scenario"] == scenario],
        key=lambda row: int(row["storage_rack_count"]),
    )


def _build_findings(
    config: CapacityScalabilityConfig,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    control = _scenario_rows(rows, FIXED_FOOTPRINT)
    growing = _scenario_rows(rows, GROWING_FOOTPRINT)
    first = growing[0]
    last = growing[-1]
    crossings = {}
    for loss in (0.10, 0.20, 0.30, 0.50):
        crossing = next(
            (
                row
                for row in growing
                if row["throughput_loss_mean"] >= loss
            ),
            None,
        )
        crossings[f"{int(loss * 100)}_percent_loss"] = (
            _finding_row(crossing) if crossing else None
        )
    return {
        "baseline": _finding_row(first),
        "largest_growing_footprint": _finding_row(last),
        "largest_fixed_footprint_control": _finding_row(control[-1]),
        "crossings": crossings,
        "growth": {
            "rack_multiplier": (
                config.storage_rack_counts[-1]
                / config.storage_rack_counts[0]
            ),
            "platter_slot_multiplier": (
                last["platter_slot_count_mean"]
                / first["platter_slot_count_mean"]
            ),
            "half_panel_length_multiplier": (
                last["half_panel_length_m_mean"]
                / first["half_panel_length_m_mean"]
            ),
            "movement_time_multiplier": (
                last["avg_shuttle_movement_s_mean"]
                / first["avg_shuttle_movement_s_mean"]
            ),
        },
        "interpretation": (
            "The fixed-footprint control isolates platter-count growth. "
            "The growing-footprint curve adds physical reach distance while "
            "holding work and active resources fixed."
        ),
    }


def _finding_row(row: dict[str, Any]) -> dict[str, float]:
    return {
        "storage_rack_count": int(row["storage_rack_count"]),
        "platter_slot_count": row["platter_slot_count_mean"],
        "half_panel_length_m": row["half_panel_length_m_mean"],
        "normalized_throughput": row["normalized_throughput_mean"],
        "throughput_loss": row["throughput_loss_mean"],
        "drive_makespan_s": row["drive_makespan_s_mean"],
        "avg_shuttle_movement_s": row[
            "avg_shuttle_movement_s_mean"
        ],
        "movement_time_share": row["movement_time_share_mean"],
        "reader_service_s": row["avg_reader_service_s_mean"],
        "reader_service_time_share": row[
            "reader_service_time_share_mean"
        ],
        "reader_read_s": row["avg_reader_read_s_mean"],
        "reader_read_time_share": row["reader_read_time_share_mean"],
        "reader_load_unload_s": row[
            "avg_reader_load_unload_s_mean"
        ],
        "reader_load_unload_time_share": row[
            "reader_load_unload_time_share_mean"
        ],
        "storage_handling_s": row["avg_storage_handling_s_mean"],
        "storage_handling_time_share": row[
            "storage_handling_time_share_mean"
        ],
        "reader_utilization": row["reader_utilization_mean"],
    }


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_report(
    path: Path,
    config: CapacityScalabilityConfig,
    result: CapacityScalabilityResult,
) -> None:
    findings = result.findings
    growing = findings["largest_growing_footprint"]
    control = findings["largest_fixed_footprint_control"]
    growth = findings["growth"]
    lines = [
        "# Capacity Scalability Pilot",
        "",
        "## 問題",
        "",
        "固定 reader 與 shuttle 數量時，增加 platter slots、storage racks "
        "與 panel 長度，是否會因 shuttle transport 增加而降低效能？",
        "",
        "## 控制條件",
        "",
        f"- 固定 {config.reader_count} readers 與 "
        f"{config.shuttle_count} shuttles。",
        f"- 每次固定 {config.workload.task_count} 個互不重複的 "
        f"{config.workload.request_size_bytes / MIB:.0f} MiB platter tasks。",
        f"- 每個 service lane 恰好分配 "
        f"{config.workload.task_count // config.zone_count} 個 tasks。",
        f"- 測試 storage-rack scale："
        f"{', '.join(str(value) for value in config.storage_rack_counts)}。",
        "- `fixed_footprint_control`：slots 增加，但 half-panel 長度固定。",
        "- `growing_footprint`：slots 與 half-panel 長度隨 rack 數同比增加。",
        "- 所有 scales 使用 paired normalized locations；不包含 skew、merge、"
        "request reordering、collision 或 controller CPU cost。",
        "",
        "## 主要結果",
        "",
        f"- 最大規模相對最小規模增加 {growth['rack_multiplier']:.0f}x racks、"
        f"{growth['platter_slot_multiplier']:.0f}x platter slots 與 "
        f"{growth['half_panel_length_multiplier']:.0f}x physical length。",
        f"- Growing-footprint throughput 保留 "
        f"{growing['normalized_throughput'] * 100:.1f}%，"
        f"損失 {growing['throughput_loss'] * 100:.1f}%。",
        f"- 平均 shuttle movement time 增加為 "
        f"{growth['movement_time_multiplier']:.2f}x，"
        f"在最大規模占 cycle time "
        f"{growing['movement_time_share'] * 100:.1f}%。",
        f"- Reader utilization 從 "
        f"{findings['baseline']['reader_utilization'] * 100:.1f}% 降至 "
        f"{growing['reader_utilization'] * 100:.1f}%。",
        f"- 本輪固定每筆 request 為 "
        f"{config.workload.request_size_bytes / MIB:.0f} MiB；每片 platter 的 "
        f"reader read time 平均為 {growing['reader_read_s']:.2f} 秒。真實 "
        "read time 會隨 request bytes 改變。",
        f"- Reader load/unload 固定為 "
        f"{growing['reader_load_unload_s']:.2f} 秒。Reader read 與 "
        "load/unload 合計占完整 cycle 的比例從 "
        f"{findings['baseline']['reader_service_time_share'] * 100:.1f}% "
        f"降至 {growing['reader_service_time_share'] * 100:.1f}%。",
        f"- 固定 footprint control 在最大 platter count 仍保留 "
        f"{control['normalized_throughput'] * 100:.1f}% throughput。",
        "",
        "## 解讀",
        "",
        "這個 pilot 支持的結論不是『platter 數量本身會降低效能』，而是："
        "當增加 platter capacity 同時擴大 physical footprint，固定數量的 "
        "reader/shuttle service lanes 會花更多 cycle time 在 media transport，"
        "降低 reader 的有效使用率與 batch throughput。",
        "",
        "## 限制",
        "",
        "- 每個 reader 與 shuttle 被建模為一條 direct fetch/read/return service lane。",
        "- 未建模 shuttle collision、共享 feeder buffer、reader reassignment 或 prefetch。",
        "- Controller 排程成本設為零，因此觀察到的退化只來自物理 movement。",
        "- 結果是 mechanism pilot，不是 production Silica capacity forecast。",
        "",
        "## Figure guide",
        "",
        "- `fig1_capacity_scaling_performance`：固定 footprint control 與 growing footprint 的效能差異。",
        "- `fig2_why_capacity_scaling_degrades`：movement time 增加與 reader utilization 下降。",
        "- `fig3_time_breakdown`：每片 platter 的 shuttle movement、reader "
        "read、reader load/unload 與 platter pick/place 時間及其占比。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_figures(
    result: CapacityScalabilityResult,
    figures_dir: Path,
) -> None:
    os.environ.setdefault(
        "MPLCONFIGDIR", str(Path("results/.mplconfig").resolve())
    )
    os.environ.setdefault(
        "XDG_CACHE_HOME", str(Path("results/.cache").resolve())
    )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )
    control = _scenario_rows(
        result.aggregate_rows,
        FIXED_FOOTPRINT,
    )
    growing = _scenario_rows(
        result.aggregate_rows,
        GROWING_FOOTPRINT,
    )
    racks = [row["storage_rack_count"] for row in growing]

    fig, axes = plt.subplots(1, 2, figsize=(10.2, 3.9))
    axes[0].plot(
        racks,
        [row["normalized_throughput_mean"] * 100 for row in control],
        color="#6B7280",
        marker="o",
        linewidth=2,
        label="Fixed footprint control",
    )
    axes[0].plot(
        racks,
        [row["normalized_throughput_mean"] * 100 for row in growing],
        color="#2F6B9A",
        marker="o",
        linewidth=2.2,
        label="Growing footprint",
    )
    axes[0].axhline(100, color="#C7CDD4", linewidth=1, linestyle="--")
    axes[0].set_xscale("log", base=2)
    axes[0].set_xticks(racks, [str(value) for value in racks])
    axes[0].set_xlabel("Storage-rack scale")
    axes[0].set_ylabel("Throughput retained (%)")
    axes[0].set_title("More slots are harmless until footprint grows")
    axes[0].legend(frameon=False, fontsize=8)
    _style_axis(axes[0])

    axes[1].plot(
        racks,
        [row["drive_makespan_s_mean"] / 60 for row in control],
        color="#6B7280",
        marker="o",
        linewidth=2,
        label="Fixed footprint control",
    )
    axes[1].plot(
        racks,
        [row["drive_makespan_s_mean"] / 60 for row in growing],
        color="#C46A2D",
        marker="o",
        linewidth=2.2,
        label="Growing footprint",
    )
    axes[1].set_xscale("log", base=2)
    axes[1].set_xticks(racks, [str(value) for value in racks])
    axes[1].set_xlabel("Storage-rack scale")
    axes[1].set_ylabel("Batch completion (min)")
    axes[1].set_title("Physical expansion lengthens the same batch")
    _style_axis(axes[1])
    _save(fig, figures_dir, "fig1_capacity_scaling_performance")

    fig, axes = plt.subplots(1, 2, figsize=(10.2, 3.9))
    axes[0].plot(
        racks,
        [row["avg_shuttle_movement_s_mean"] for row in growing],
        color="#2F6B9A",
        marker="o",
        linewidth=2.2,
    )
    axes[0].set_xscale("log", base=2)
    axes[0].set_xticks(racks, [str(value) for value in racks])
    axes[0].set_xlabel("Storage-rack scale")
    axes[0].set_ylabel("Movement time per platter (s)")
    axes[0].set_title("Shuttle transport grows with physical reach")
    _style_axis(axes[0])

    axes[1].plot(
        racks,
        [row["reader_utilization_mean"] * 100 for row in growing],
        color="#C46A2D",
        marker="o",
        linewidth=2.2,
    )
    axes[1].set_xscale("log", base=2)
    axes[1].set_xticks(racks, [str(value) for value in racks])
    axes[1].set_xlabel("Storage-rack scale")
    axes[1].set_ylabel("Reader utilization (%)")
    axes[1].set_title("Readers spend more time waiting on media cycles")
    _style_axis(axes[1])
    _save(fig, figures_dir, "fig2_why_capacity_scaling_degrades")

    positions = list(range(len(racks)))
    movement_s = [
        row["avg_shuttle_movement_s_mean"] for row in growing
    ]
    reader_read_s = [row["avg_reader_read_s_mean"] for row in growing]
    reader_load_unload_s = [
        row["avg_reader_load_unload_s_mean"] for row in growing
    ]
    handling_s = [
        row["avg_storage_handling_s_mean"] for row in growing
    ]
    movement_share = [
        row["movement_time_share_mean"] * 100 for row in growing
    ]
    reader_read_share = [
        row["reader_read_time_share_mean"] * 100 for row in growing
    ]
    reader_load_unload_share = [
        row["reader_load_unload_time_share_mean"] * 100
        for row in growing
    ]
    handling_share = [
        row["storage_handling_time_share_mean"] * 100 for row in growing
    ]

    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.1))
    axes[0].bar(
        positions,
        movement_s,
        color="#2F6B9A",
        label="Shuttle movement time",
    )
    axes[0].bar(
        positions,
        reader_read_s,
        bottom=movement_s,
        color="#C46A2D",
        label="Reader read time",
    )
    first_bottom = [
        movement + reader
        for movement, reader in zip(movement_s, reader_read_s)
    ]
    axes[0].bar(
        positions,
        reader_load_unload_s,
        bottom=first_bottom,
        color="#E3A36A",
        label="Reader load/unload time",
    )
    second_bottom_s = [
        bottom + load_unload
        for bottom, load_unload in zip(
            first_bottom, reader_load_unload_s
        )
    ]
    axes[0].bar(
        positions,
        handling_s,
        bottom=second_bottom_s,
        color="#7A828D",
        label="Platter pick/place time",
    )
    axes[0].set_xticks(positions, [str(value) for value in racks])
    axes[0].set_xlabel("Capacity scale")
    axes[0].set_ylabel("Time per platter (s)")
    axes[0].set_title("Only movement time grows")
    axes[0].legend(frameon=False, fontsize=8)
    _style_axis(axes[0])

    axes[1].bar(
        positions,
        movement_share,
        color="#2F6B9A",
        label="Shuttle movement time",
    )
    axes[1].bar(
        positions,
        reader_read_share,
        bottom=movement_share,
        color="#C46A2D",
        label="Reader read time",
    )
    second_bottom = [
        movement + reader
        for movement, reader in zip(movement_share, reader_read_share)
    ]
    axes[1].bar(
        positions,
        reader_load_unload_share,
        bottom=second_bottom,
        color="#E3A36A",
        label="Reader load/unload time",
    )
    third_bottom = [
        bottom + load_unload
        for bottom, load_unload in zip(
            second_bottom, reader_load_unload_share
        )
    ]
    axes[1].bar(
        positions,
        handling_share,
        bottom=third_bottom,
        color="#7A828D",
        label="Platter pick/place time",
    )
    axes[1].set_xticks(positions, [str(value) for value in racks])
    axes[1].set_xlabel("Capacity scale")
    axes[1].set_ylabel("Share of platter cycle (%)")
    axes[1].set_ylim(0, 100)
    axes[1].set_title("Reader time becomes a smaller share")
    for index in (0, len(positions) - 1):
        axes[1].text(
            positions[index],
            movement_share[index] / 2,
            f"{movement_share[index]:.1f}%",
            ha="center",
            va="center",
            color="white",
            fontsize=9,
            fontweight="bold",
        )
        axes[1].text(
            positions[index],
            movement_share[index]
            + (reader_read_share[index] + reader_load_unload_share[index]) / 2,
            "Reader total\n"
            f"{reader_read_share[index] + reader_load_unload_share[index]:.1f}%",
            ha="center",
            va="center",
            color="#7A3510",
            fontsize=8.5,
            fontweight="bold",
            bbox={
                "boxstyle": "round,pad=0.25",
                "facecolor": "white",
                "edgecolor": "#C46A2D",
                "linewidth": 1.0,
                "alpha": 0.96,
            },
        )
    _style_axis(axes[1])
    _save(
        fig,
        figures_dir,
        "fig3_time_breakdown",
        note=(
            "Assumption: fixed 64 MiB request per platter. Reader read time "
            "varies with request size; bars report the mean in this experiment."
        ),
    )


def _style_axis(ax: Any) -> None:
    ax.grid(True, axis="y", color="#D7DEE8", linewidth=0.8)
    ax.grid(False, axis="x")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#9AA5B1")
    ax.spines["bottom"].set_color("#9AA5B1")


def _save(
    fig: Any,
    figures_dir: Path,
    name: str,
    note: str | None = None,
) -> None:
    if note:
        fig.tight_layout(rect=(0, 0.08, 1, 1))
        fig.text(
            0.5,
            0.02,
            note,
            ha="center",
            va="bottom",
            fontsize=8,
            color="#5F6B76",
        )
    else:
        fig.tight_layout()
    fig.savefig(figures_dir / f"{name}.pdf")
    fig.savefig(figures_dir / f"{name}.png", dpi=300)
    import matplotlib.pyplot as plt

    plt.close(fig)
