from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import csv
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from .azure_static_zone_pilot import AzureBatchAccess, _hash_u64, _load_batch, _sha256
from .capacity_scalability import (
    FIXED_FOOTPRINT,
    GROWING_FOOTPRINT,
    CapacityGeometryConfig,
)
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


@dataclass(frozen=True)
class AzureCapacityScalabilityConfig:
    output_dir: Path
    batch_path: Path
    expected_batch_sha256: str
    seeds: tuple[int, ...]
    storage_rack_counts: tuple[int, ...]
    reader_count: int
    shuttle_count: int
    virtual_platter_count: int
    geometry: CapacityGeometryConfig
    movement: PanelMovementConfig
    timing: PanelTimingConfig

    @property
    def zone_count(self) -> int:
        return (self.geometry.levels // self.geometry.zone_height_racks) * 2

    def validate(self) -> None:
        self.geometry.validate()
        self.movement.validate()
        self.timing.validate()
        if not self.batch_path.is_file():
            raise ValueError(f"Azure batch does not exist: {self.batch_path}")
        if len(self.expected_batch_sha256) != 64:
            raise ValueError("expected_batch_sha256 must contain 64 hex characters")
        try:
            int(self.expected_batch_sha256, 16)
        except ValueError as exc:
            raise ValueError("expected_batch_sha256 must be hexadecimal") from exc
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
            raise ValueError("reader_count must match the service-lane count")
        if self.shuttle_count != self.zone_count:
            raise ValueError("shuttle_count must match the service-lane count")
        if self.virtual_platter_count <= 0:
            raise ValueError("virtual_platter_count must be positive")
        if self.virtual_platter_count % self.zone_count != 0:
            raise ValueError(
                "virtual_platter_count must divide evenly across service lanes"
            )
        minimum_lane_capacity = (
            self.geometry.zone_height_racks
            * self.geometry.slots_per_half_per_rack
            * self.storage_rack_counts[0]
        )
        if self.virtual_platter_count // self.zone_count > minimum_lane_capacity:
            raise ValueError("minimum rack scale cannot hold the virtual platters")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "output_dir": portable_path(self.output_dir),
            "batch_path": portable_path(self.batch_path),
            "expected_batch_sha256": self.expected_batch_sha256,
            "seeds": list(self.seeds),
            "storage_rack_counts": list(self.storage_rack_counts),
            "reader_count": self.reader_count,
            "shuttle_count": self.shuttle_count,
            "virtual_platter_count": self.virtual_platter_count,
            "geometry": asdict(self.geometry),
            "movement": asdict(self.movement),
            "timing": asdict(self.timing),
            "experiment_scope": {
                "azure_trace_sizes_and_reuse": True,
                "batch_wide_platter_merge": True,
                "fixed_logical_and_physical_work": True,
                "paired_normalized_locations": True,
                "all_requests_arrive_at_batch_start": True,
                "original_interarrival_times_modeled": False,
                "prefetch": False,
                "request_reordering": False,
                "controller_cpu_cost": False,
                "shuttle_collision": False,
            },
        }


@dataclass(frozen=True)
class VirtualPlatterWork:
    virtual_platter_id: int
    first_request_index: int
    size_bytes: int
    logical_request_count: int
    unique_blob_version_count: int


@dataclass(frozen=True)
class AzureCapacityScalabilityResult:
    source: dict[str, Any]
    platter_rows: list[dict[str, Any]]
    run_rows: list[dict[str, Any]]
    aggregate_rows: list[dict[str, Any]]
    validation: dict[str, Any]
    findings: dict[str, Any]


def load_azure_capacity_scalability_config(
    path: str | Path,
) -> AzureCapacityScalabilityConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    root = repository_root_for_config(config_path)
    output_dir = _resolve_path(raw["output_dir"], root)
    config = AzureCapacityScalabilityConfig(
        output_dir=output_dir,
        batch_path=_resolve_path(raw["batch_path"], root),
        expected_batch_sha256=str(raw["expected_batch_sha256"]).lower(),
        seeds=tuple(int(seed) for seed in raw["seeds"]),
        storage_rack_counts=tuple(
            int(value) for value in raw["storage_rack_counts"]
        ),
        reader_count=int(raw["reader_count"]),
        shuttle_count=int(raw["shuttle_count"]),
        virtual_platter_count=int(raw["virtual_platter_count"]),
        geometry=CapacityGeometryConfig(**raw["geometry"]),
        movement=PanelMovementConfig(**raw["movement"]),
        timing=PanelTimingConfig(**raw["timing"]),
    )
    config.validate()
    return config


def build_virtual_platter_work(
    accesses: list[AzureBatchAccess],
    virtual_platter_count: int,
    seed: int,
) -> list[VirtualPlatterWork]:
    if virtual_platter_count <= 0:
        raise ValueError("virtual_platter_count must be positive")
    unique_sizes: dict[tuple[str, str], int] = {}
    for access in accesses:
        existing = unique_sizes.setdefault(access.object_key, access.size_bytes)
        if existing != access.size_bytes:
            raise ValueError(
                "blob version has inconsistent sizes within the batch: "
                f"{access.object_key}"
            )
    if len(unique_sizes) < virtual_platter_count:
        raise ValueError(
            "virtual_platter_count cannot exceed unique blob-version count"
        )

    ordered_keys = sorted(
        unique_sizes,
        key=lambda key: (_hash_u64(seed, *key), key),
    )
    object_to_platter = {
        key: rank % virtual_platter_count
        for rank, key in enumerate(ordered_keys)
    }
    groups = [
        {
            "first_request_index": len(accesses),
            "size_bytes": 0,
            "logical_request_count": 0,
            "unique_blob_version_count": 0,
        }
        for _ in range(virtual_platter_count)
    ]
    for key, size_bytes in unique_sizes.items():
        group = groups[object_to_platter[key]]
        group["size_bytes"] += size_bytes
        group["unique_blob_version_count"] += 1
    for access in accesses:
        group = groups[object_to_platter[access.object_key]]
        group["logical_request_count"] += 1
        group["first_request_index"] = min(
            group["first_request_index"], access.index
        )

    work = [
        VirtualPlatterWork(
            virtual_platter_id=virtual_platter_id,
            first_request_index=int(group["first_request_index"]),
            size_bytes=int(group["size_bytes"]),
            logical_request_count=int(group["logical_request_count"]),
            unique_blob_version_count=int(group["unique_blob_version_count"]),
        )
        for virtual_platter_id, group in enumerate(groups)
    ]
    return sorted(work, key=lambda item: item.first_request_index)


def run_azure_capacity_scalability(
    config: AzureCapacityScalabilityConfig,
) -> AzureCapacityScalabilityResult:
    config.validate()
    observed_sha256 = _sha256(config.batch_path)
    if observed_sha256 != config.expected_batch_sha256:
        raise ValueError(
            "batch checksum mismatch: "
            f"expected {config.expected_batch_sha256}, got {observed_sha256}"
        )
    accesses = _load_batch(config.batch_path)
    unique_objects = _unique_object_sizes(accesses)
    source = {
        "dataset": "Azure Functions Blob Access Trace 2020",
        "batch_path": portable_path(config.batch_path),
        "batch_sha256": observed_sha256,
        "logical_request_count": len(accesses),
        "logical_bytes": sum(access.size_bytes for access in accesses),
        "unique_blob_versions": len(unique_objects),
        "unique_blob_version_bytes": sum(unique_objects.values()),
        "repeated_blob_version_requests": len(accesses) - len(unique_objects),
        "batch_trace_span_s": _batch_span_s(config.batch_path),
    }

    run_rows: list[dict[str, Any]] = []
    platter_rows: list[dict[str, Any]] = []
    failures: list[str] = []
    signatures: dict[int, str] = {}
    for seed in config.seeds:
        work = build_virtual_platter_work(
            accesses, config.virtual_platter_count, seed
        )
        signatures[seed] = _work_signature(work)
        platter_rows.extend(
            {
                "seed": seed,
                "virtual_platter_id": item.virtual_platter_id,
                "service_lane": item.virtual_platter_id % config.zone_count,
                "first_request_index": item.first_request_index,
                "size_bytes": item.size_bytes,
                "logical_request_count": item.logical_request_count,
                "unique_blob_version_count": item.unique_blob_version_count,
            }
            for item in work
        )
        _validate_work(config, source, work, seed, failures)
        for scenario in (FIXED_FOOTPRINT, GROWING_FOOTPRINT):
            for rack_count in config.storage_rack_counts:
                simulator = PanelStaticZoneSimulator(
                    _panel_config(config, seed, rack_count, scenario)
                )
                requests = _materialize_work(config, simulator, work)
                _validate_requests(
                    config,
                    source,
                    work,
                    requests,
                    seed,
                    rack_count,
                    scenario,
                    failures,
                )
                result = simulator.run(requests)
                run_rows.append(
                    _run_row(config, source, scenario, seed, rack_count, result)
                )

    _normalize_rows(config, run_rows)
    aggregate_rows = _aggregate_rows(run_rows)
    _validate_aggregate(config, aggregate_rows, failures)
    if failures:
        raise RuntimeError(
            "azure-capacity-scalability validation failed: "
            + "; ".join(failures)
        )
    findings = _build_findings(config, aggregate_rows)
    return AzureCapacityScalabilityResult(
        source=source,
        platter_rows=platter_rows,
        run_rows=run_rows,
        aggregate_rows=aggregate_rows,
        validation={
            "passed": True,
            "checked_runs": len(run_rows),
            "paired_seeds": len(config.seeds),
            "batch_checksum_matches": True,
            "fixed_logical_requests": source["logical_request_count"],
            "fixed_logical_bytes": source["logical_bytes"],
            "fixed_unique_blob_versions": source["unique_blob_versions"],
            "fixed_unique_blob_version_bytes": source[
                "unique_blob_version_bytes"
            ],
            "fixed_physical_tasks": config.virtual_platter_count,
            "fixed_readers": config.reader_count,
            "fixed_shuttles": config.shuttle_count,
            "balanced_physical_tasks_per_service_lane": True,
            "paired_work_signatures": signatures,
            "fixed_footprint_control_is_stable": True,
            "growing_footprint_movement_is_monotonic": True,
            "failures": [],
        },
        findings=findings,
    )


def write_azure_capacity_scalability_outputs(
    config: AzureCapacityScalabilityConfig,
    result: AzureCapacityScalabilityResult,
) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    _write_rows(
        config.output_dir / "virtual_platter_summary.csv",
        result.platter_rows,
    )
    _write_rows(config.output_dir / "run_summary.csv", result.run_rows)
    _write_rows(
        config.output_dir / "aggregate_summary.csv", result.aggregate_rows
    )
    with (config.output_dir / "summary.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(
            {
                "config": config.to_json_dict(),
                "source": result.source,
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
        config.output_dir / "AZURE_CAPACITY_SCALABILITY_ANALYSIS_ZH.md",
        config,
        result,
    )
    figures_dir = config.output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    _write_figures(result, figures_dir)


def _resolve_path(value: str, root: Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _unique_object_sizes(
    accesses: list[AzureBatchAccess],
) -> dict[tuple[str, str], int]:
    result: dict[tuple[str, str], int] = {}
    for access in accesses:
        existing = result.setdefault(access.object_key, access.size_bytes)
        if existing != access.size_bytes:
            raise ValueError(f"inconsistent blob-version size: {access.object_key}")
    return result


def _batch_span_s(path: Path) -> float:
    first: int | None = None
    last: int | None = None
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            arrival_ms = int(row["ArrivalMs"])
            if first is None:
                first = arrival_ms
            last = arrival_ms
    return ((last or 0) - (first or 0)) / 1000.0


def _panel_config(
    config: AzureCapacityScalabilityConfig,
    seed: int,
    rack_count: int,
    scenario: str,
) -> PanelStaticZoneConfig:
    slots_per_half = config.geometry.slots_per_half_per_rack * rack_count
    if scenario == GROWING_FOOTPRINT:
        half_panel_length_m = config.geometry.rack_length_m * rack_count
    elif scenario == FIXED_FOOTPRINT:
        half_panel_length_m = config.geometry.fixed_footprint_half_length_m
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
            batch_size=config.virtual_platter_count,
            request_size_bytes=1,
            placement="uniform_round_robin",
            request_merge=False,
        ),
    )


def _materialize_work(
    config: AzureCapacityScalabilityConfig,
    simulator: PanelStaticZoneSimulator,
    work: list[VirtualPlatterWork],
) -> list[PanelRequest]:
    tasks_per_lane = config.virtual_platter_count // config.zone_count
    slots_per_half = simulator.geometry.slots_per_half
    requests: list[PanelRequest] = []
    for item in work:
        zone_id = item.virtual_platter_id % config.zone_count
        lane_rank = item.virtual_platter_id // config.zone_count
        normalized_distance = (lane_rank + 0.5) / tasks_per_lane
        reader_relative_slot = min(
            slots_per_half - 1,
            int(normalized_distance * slots_per_half),
        )
        side = simulator.zones[zone_id].side
        slot = (
            reader_relative_slot
            if side == "left"
            else slots_per_half - 1 - reader_relative_slot
        )
        local_level = _hash_u64(
            simulator.config.seed, "level", str(item.virtual_platter_id)
        ) % config.geometry.zone_height_racks
        request = simulator.make_request(
            request_index=item.first_request_index,
            zone_id=zone_id,
            local_level=local_level,
            slot_in_half=slot,
            size_bytes=item.size_bytes,
            arrival_s=0.0,
        )
        requests.append(
            replace(
                request,
                merged_request_count=item.logical_request_count,
            )
        )
    return sorted(requests, key=lambda request: request.request_index)


def _work_signature(work: list[VirtualPlatterWork]) -> str:
    digest = hashlib.sha256()
    for item in sorted(work, key=lambda value: value.virtual_platter_id):
        digest.update(
            (
                f"{item.virtual_platter_id}:{item.first_request_index}:"
                f"{item.size_bytes}:{item.logical_request_count}:"
                f"{item.unique_blob_version_count}\n"
            ).encode("ascii")
        )
    return digest.hexdigest()


def _validate_work(
    config: AzureCapacityScalabilityConfig,
    source: dict[str, Any],
    work: list[VirtualPlatterWork],
    seed: int,
    failures: list[str],
) -> None:
    label = f"seed {seed}"
    if len(work) != config.virtual_platter_count:
        failures.append(f"{label}: physical task count changed")
    if sum(item.logical_request_count for item in work) != source[
        "logical_request_count"
    ]:
        failures.append(f"{label}: logical request count changed")
    if sum(item.size_bytes for item in work) != source[
        "unique_blob_version_bytes"
    ]:
        failures.append(f"{label}: unique bytes changed")
    if sum(item.unique_blob_version_count for item in work) != source[
        "unique_blob_versions"
    ]:
        failures.append(f"{label}: unique blob-version count changed")


def _validate_requests(
    config: AzureCapacityScalabilityConfig,
    source: dict[str, Any],
    work: list[VirtualPlatterWork],
    requests: list[PanelRequest],
    seed: int,
    rack_count: int,
    scenario: str,
    failures: list[str],
) -> None:
    label = f"seed {seed} {scenario} racks {rack_count}"
    if len(requests) != config.virtual_platter_count:
        failures.append(f"{label}: physical task count changed")
    if sum(request.merged_request_count for request in requests) != source[
        "logical_request_count"
    ]:
        failures.append(f"{label}: logical request count changed")
    if sum(request.size_bytes for request in requests) != source[
        "unique_blob_version_bytes"
    ]:
        failures.append(f"{label}: unique bytes changed")
    if len({request.platter_id for request in requests}) != len(requests):
        failures.append(f"{label}: physical platter locations overlap")
    expected_per_lane = config.virtual_platter_count // config.zone_count
    lane_counts = [
        sum(request.zone_id == zone_id for request in requests)
        for zone_id in range(config.zone_count)
    ]
    if any(count != expected_per_lane for count in lane_counts):
        failures.append(f"{label}: physical tasks are not balanced by lane")
    expected_work = sorted(
        (
            item.first_request_index,
            item.size_bytes,
            item.logical_request_count,
            item.virtual_platter_id % config.zone_count,
        )
        for item in work
    )
    observed_work = sorted(
        (
            request.request_index,
            request.size_bytes,
            request.merged_request_count,
            request.zone_id,
        )
        for request in requests
    )
    if expected_work != observed_work:
        failures.append(f"{label}: paired request work changed")


def _run_row(
    config: AzureCapacityScalabilityConfig,
    source: dict[str, Any],
    scenario: str,
    seed: int,
    rack_count: int,
    result: Any,
) -> dict[str, Any]:
    summary = result.summary
    movement_avg = summary["aggregate_component_avg_s"]["shuttle_movement_s"]
    active_avg = summary["avg_cycle_s_per_service"]
    zone_work = [float(row["active_cycle_s"]) for row in result.zone_rows]
    slots_per_half = config.geometry.slots_per_half_per_rack * rack_count
    half_panel_length_m = (
        config.geometry.rack_length_m * rack_count
        if scenario == GROWING_FOOTPRINT
        else config.geometry.fixed_footprint_half_length_m
    )
    return {
        "seed": seed,
        "scenario": scenario,
        "storage_rack_count": rack_count,
        "half_panel_length_m": half_panel_length_m,
        "slots_per_half": slots_per_half,
        "platter_slot_count": config.geometry.levels * 2 * slots_per_half,
        "reader_count": summary["reader_count"],
        "shuttle_count": summary["shuttle_count"],
        "physical_task_count": summary["service_operation_count"],
        "logical_request_count": summary["request_count"],
        "logical_bytes": source["logical_bytes"],
        "physical_unique_bytes": sum(
            detail.size_bytes for detail in result.details
        ),
        "unique_blob_versions": source["unique_blob_versions"],
        "drive_makespan_s": summary["drive_makespan_s"],
        "system_drain_s": summary["system_drain_s"],
        "throughput_req_per_s": summary["throughput_req_per_s"],
        "throughput_physical_tasks_per_s": summary[
            "throughput_service_ops_per_s"
        ],
        "throughput_mib_per_s": summary["throughput_mib_per_s"],
        "latency_p95_s": summary["latency_p95_s"],
        "latency_p99_s": summary["latency_p99_s"],
        "avg_cycle_s": active_avg,
        "avg_shuttle_movement_s": movement_avg,
        "avg_fixed_mechanical_s": summary["aggregate_component_avg_s"][
            "fixed_mechanical_s"
        ],
        "avg_reader_transfer_s": summary["aggregate_component_avg_s"][
            "reader_data_transfer_s"
        ],
        "movement_time_share": movement_avg / active_avg if active_avg else 0.0,
        "reader_utilization": summary["reader_utilization_avg"],
        "shuttle_utilization": summary["shuttle_utilization_avg"],
        "horizontal_distance_m_per_task": (
            summary["horizontal_distance_m"]
            / summary["service_operation_count"]
        ),
        "busiest_lane_work_over_mean": max(zone_work) / mean(zone_work),
        "capacity_efficiency": summary["static_capacity_efficiency"],
    }


def _normalize_rows(
    config: AzureCapacityScalabilityConfig,
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


def _aggregate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["scenario"]), int(row["storage_rack_count"]))
        groups.setdefault(key, []).append(row)
    identity = {"seed", "scenario", "storage_rack_count"}
    aggregate_rows = []
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
            aggregate[f"{field}_ci95"] = 1.96 * std / math.sqrt(len(values))
        aggregate_rows.append(aggregate)
    return aggregate_rows


def _scenario_rows(
    rows: list[dict[str, Any]], scenario: str
) -> list[dict[str, Any]]:
    return sorted(
        [row for row in rows if row["scenario"] == scenario],
        key=lambda row: int(row["storage_rack_count"]),
    )


def _validate_aggregate(
    config: AzureCapacityScalabilityConfig,
    rows: list[dict[str, Any]],
    failures: list[str],
) -> None:
    if len(rows) != len(config.storage_rack_counts) * 2:
        failures.append("aggregate scenario/rack count changed")
    for row in rows:
        if row["physical_task_count_mean"] != config.virtual_platter_count:
            failures.append("a sweep point changed physical task count")
        if row["reader_count_mean"] != config.reader_count:
            failures.append("a sweep point changed reader count")
        if row["shuttle_count_mean"] != config.shuttle_count:
            failures.append("a sweep point changed shuttle count")
    control = _scenario_rows(rows, FIXED_FOOTPRINT)
    growing = _scenario_rows(rows, GROWING_FOOTPRINT)
    retained = [row["normalized_throughput_mean"] for row in control]
    if max(retained) - min(retained) > 0.02:
        failures.append("fixed-footprint control changed by more than 2%")
    movement = [row["avg_shuttle_movement_s_mean"] for row in growing]
    if any(right + 1e-9 < left for left, right in zip(movement, movement[1:])):
        failures.append("growing-footprint movement is not monotonic")
    throughput = [row["normalized_throughput_mean"] for row in growing]
    if any(right > left + 1e-9 for left, right in zip(throughput, throughput[1:])):
        failures.append("growing-footprint throughput is not monotonic")


def _finding_row(row: dict[str, Any]) -> dict[str, float]:
    return {
        "storage_rack_count": int(row["storage_rack_count"]),
        "platter_slot_count": row["platter_slot_count_mean"],
        "half_panel_length_m": row["half_panel_length_m_mean"],
        "normalized_throughput": row["normalized_throughput_mean"],
        "throughput_loss": row["throughput_loss_mean"],
        "drive_makespan_s": row["drive_makespan_s_mean"],
        "avg_shuttle_movement_s": row["avg_shuttle_movement_s_mean"],
        "movement_time_share": row["movement_time_share_mean"],
        "reader_utilization": row["reader_utilization_mean"],
        "throughput_req_per_s": row["throughput_req_per_s_mean"],
        "throughput_mib_per_s": row["throughput_mib_per_s_mean"],
        "busiest_lane_work_over_mean": row[
            "busiest_lane_work_over_mean_mean"
        ],
    }


def _build_findings(
    config: AzureCapacityScalabilityConfig,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    control = _scenario_rows(rows, FIXED_FOOTPRINT)
    growing = _scenario_rows(rows, GROWING_FOOTPRINT)
    first = growing[0]
    last = growing[-1]
    crossings = {}
    for loss in (0.10, 0.20, 0.30, 0.50):
        crossing = next(
            (row for row in growing if row["throughput_loss_mean"] >= loss),
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
            "movement_time_multiplier": (
                last["avg_shuttle_movement_s_mean"]
                / first["avg_shuttle_movement_s_mean"]
            ),
        },
    }


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_report(
    path: Path,
    config: AzureCapacityScalabilityConfig,
    result: AzureCapacityScalabilityResult,
) -> None:
    source = result.source
    findings = result.findings
    baseline = findings["baseline"]
    growing = findings["largest_growing_footprint"]
    control = findings["largest_fixed_footprint_control"]
    lines = [
        "# Azure Trace-driven Capacity Scalability",
        "",
        "## 這次實驗回答什麼",
        "",
        "固定 reader、shuttle 與 batch work，只增加 platter slots 與 rack "
        "physical footprint 時，同一批 Azure Blob accesses 是否會變慢？",
        "",
        "## Dataset 與 mapping",
        "",
        f"- Dataset：{source['dataset']} 的 deterministic head-100k read batch。",
        f"- 原始 batch：{source['logical_request_count']:,} requests，"
        f"跨 {source['batch_trace_span_s'] / 3600:.2f} 小時。",
        f"- 包含 {source['unique_blob_versions']:,} unique blob versions；"
        f"重複 version requests 為 {source['repeated_blob_version_requests']:,} "
        f"({source['repeated_blob_version_requests'] / source['logical_request_count'] * 100:.2f}%)。",
        f"- Batch-wide merge 後固定為 {config.virtual_platter_count} 個 "
        "virtual platter services，讀取各 platter 上的 unique object bytes。",
        f"- 每個 scale 的 physical unique data 固定為 "
        f"{source['unique_blob_version_bytes'] / MIB:.1f} MiB。",
        "- Object-to-platter placement 是 deterministic uniform packing；"
        "Azure trace 沒有提供 Silica 實體 platter address。",
        "- 原始 interarrival time 未放進 simulator；100,000 requests 在 batch "
        "開始時共同可見。",
        "",
        "## 主要結果",
        "",
        f"- Growing footprint 從 1x 增至 "
        f"{config.storage_rack_counts[-1]}x 時，throughput 保留 "
        f"{growing['normalized_throughput'] * 100:.1f}%，損失 "
        f"{growing['throughput_loss'] * 100:.1f}%。",
        f"- Batch completion 從 {baseline['drive_makespan_s'] / 60:.2f} "
        f"分鐘增至 {growing['drive_makespan_s'] / 60:.2f} 分鐘。",
        f"- 平均 movement time 增加 "
        f"{findings['growth']['movement_time_multiplier']:.2f}x，"
        f"最大規模占 cycle time {growing['movement_time_share'] * 100:.1f}%。",
        f"- Reader utilization 從 {baseline['reader_utilization'] * 100:.1f}% "
        f"降至 {growing['reader_utilization'] * 100:.1f}%。",
        f"- Fixed-footprint control 在最大 slots 下仍保留 "
        f"{control['normalized_throughput'] * 100:.1f}% throughput。",
        "",
        "## 解讀限制",
        "",
        "這個結果使用 Azure 的 request identity、reuse 與 object sizes，但實體 "
        "platter placement 是 controlled mapping。它支持 physical reach 增長會讓 "
        "trace-calibrated batch 付出更多 transport time；不代表 Azure production "
        "placement，也不宣稱已包含 prefetch、collision 或 online arrivals。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_figures(
    result: AzureCapacityScalabilityResult,
    figures_dir: Path,
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(Path("results/.mplconfig").resolve()))
    os.environ.setdefault("XDG_CACHE_HOME", str(Path("results/.cache").resolve()))
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
    control = _scenario_rows(result.aggregate_rows, FIXED_FOOTPRINT)
    growing = _scenario_rows(result.aggregate_rows, GROWING_FOOTPRINT)
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
    axes[0].set_title("Same Azure batch, longer physical reach")
    axes[0].legend(frameon=False, fontsize=8)
    _style_axis(axes[0])

    axes[1].plot(
        racks,
        [row["drive_makespan_s_mean"] / 60 for row in control],
        color="#6B7280",
        marker="o",
        linewidth=2,
    )
    axes[1].plot(
        racks,
        [row["drive_makespan_s_mean"] / 60 for row in growing],
        color="#C46A2D",
        marker="o",
        linewidth=2.2,
    )
    axes[1].set_xscale("log", base=2)
    axes[1].set_xticks(racks, [str(value) for value in racks])
    axes[1].set_xlabel("Storage-rack scale")
    axes[1].set_ylabel("Batch completion (min)")
    axes[1].set_title("Physical expansion lengthens completion")
    _style_axis(axes[1])
    _save(fig, figures_dir, "fig1_azure_capacity_scaling")

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
    axes[0].set_title("Transport dominates as reach grows")
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
    axes[1].set_title("Readers wait longer for media cycles")
    _style_axis(axes[1])
    _save(fig, figures_dir, "fig2_azure_capacity_mechanism")


def _style_axis(ax: Any) -> None:
    ax.grid(True, axis="y", color="#D7DEE8", linewidth=0.8)
    ax.grid(False, axis="x")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#9AA5B1")
    ax.spines["bottom"].set_color("#9AA5B1")


def _save(fig: Any, figures_dir: Path, name: str) -> None:
    fig.tight_layout()
    fig.savefig(figures_dir / f"{name}.pdf")
    fig.savefig(figures_dir / f"{name}.png", dpi=300)
    import matplotlib.pyplot as plt

    plt.close(fig)
