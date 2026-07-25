from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import csv
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Iterable

from .panel_static_zone import (
    PanelGeometryConfig,
    PanelMovementConfig,
    PanelStaticZoneConfig,
    PanelStaticZoneSimulator,
    PanelTimingConfig,
    PanelWorkloadConfig,
    merge_panel_requests,
)
from .trace import TraceRequest, iter_trace
from .paths import portable_path, repository_root_for_config


MIB = 1024 * 1024


@dataclass(frozen=True)
class NaturalPlacementConfig:
    name: str
    display_name: str
    family: str
    mode: str
    hash_seed: int | None = None

    def validate(self) -> None:
        if not self.name or not self.display_name or not self.family:
            raise ValueError("placement name, display_name, and family cannot be empty")
        if self.mode not in {"hash", "contiguous_lba"}:
            raise ValueError("placement mode must be 'hash' or 'contiguous_lba'")
        if self.mode == "hash" and self.hash_seed is None:
            raise ValueError("hash placement requires hash_seed")


@dataclass(frozen=True)
class NaturalTraceSkewConfig:
    output_dir: Path
    trace_path: Path
    max_read_requests: int | None
    request_count_windows: tuple[int, ...]
    time_windows_s: tuple[float, ...]
    hotspot_work_share_threshold: float
    primary_count_window: int
    primary_time_window_s: float
    heatmap_placement: str
    validation_sample_windows: int
    stripe_bytes: int
    platter_count: int
    placements: tuple[NaturalPlacementConfig, ...]
    geometry: PanelGeometryConfig
    movement: PanelMovementConfig
    timing: PanelTimingConfig

    def validate(self) -> None:
        self.geometry.validate()
        self.movement.validate()
        self.timing.validate()
        if self.max_read_requests is not None and self.max_read_requests <= 0:
            raise ValueError("max_read_requests must be positive or null")
        if not self.request_count_windows or any(value <= 0 for value in self.request_count_windows):
            raise ValueError("request_count_windows must contain positive values")
        if len(set(self.request_count_windows)) != len(self.request_count_windows):
            raise ValueError("request_count_windows cannot contain duplicates")
        if not self.time_windows_s or any(value <= 0 for value in self.time_windows_s):
            raise ValueError("time_windows_s must contain positive values")
        if len(set(self.time_windows_s)) != len(self.time_windows_s):
            raise ValueError("time_windows_s cannot contain duplicates")
        if self.primary_count_window not in self.request_count_windows:
            raise ValueError("primary_count_window must be in request_count_windows")
        if self.primary_time_window_s not in self.time_windows_s:
            raise ValueError("primary_time_window_s must be in time_windows_s")
        if not 1 / self.zone_count <= self.hotspot_work_share_threshold <= 1:
            raise ValueError("hotspot threshold must be between balanced share and 1")
        if self.validation_sample_windows <= 0:
            raise ValueError("validation_sample_windows must be positive")
        if self.stripe_bytes <= 0 or self.platter_count <= 0:
            raise ValueError("stripe_bytes and platter_count must be positive")
        expected_positions = (
            self.zone_count * self.geometry.zone_height_racks * self.geometry.slots_per_half
        )
        if self.platter_count != expected_positions:
            raise ValueError("platter_count must equal physical panel positions")
        if not self.placements:
            raise ValueError("placements cannot be empty")
        names = [placement.name for placement in self.placements]
        if len(set(names)) != len(names):
            raise ValueError("placement names cannot contain duplicates")
        for placement in self.placements:
            placement.validate()
        if self.heatmap_placement not in names:
            raise ValueError("heatmap_placement must name one configured placement")

    @property
    def zone_count(self) -> int:
        return self.geometry.levels // self.geometry.zone_height_racks * 2

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "output_dir": portable_path(self.output_dir),
            "trace_path": portable_path(self.trace_path),
            "max_read_requests": self.max_read_requests,
            "request_count_windows": list(self.request_count_windows),
            "time_windows_s": list(self.time_windows_s),
            "hotspot_work_share_threshold": self.hotspot_work_share_threshold,
            "primary_count_window": self.primary_count_window,
            "primary_time_window_s": self.primary_time_window_s,
            "heatmap_placement": self.heatmap_placement,
            "validation_sample_windows": self.validation_sample_windows,
            "stripe_bytes": self.stripe_bytes,
            "platter_count": self.platter_count,
            "placements": [asdict(placement) for placement in self.placements],
            "geometry": asdict(self.geometry),
            "movement": asdict(self.movement),
            "timing": asdict(self.timing),
        }


@dataclass(frozen=True)
class MappedNaturalRequest:
    source_index: int
    arrival_s: float
    size_bytes: int
    platter_id: int
    zone_id: int
    local_level: int
    slot_in_half: int


@dataclass(frozen=True)
class WindowComputation:
    row: dict[str, Any]
    zone_logical_counts: tuple[int, ...]
    zone_task_counts: tuple[int, ...]
    zone_work_s: tuple[float, ...]


@dataclass(frozen=True)
class NaturalTraceSkewResult:
    source_stats: dict[str, Any]
    window_rows: list[dict[str, Any]]
    placement_rows: list[dict[str, Any]]
    family_rows: list[dict[str, Any]]
    zone_rows: list[dict[str, Any]]
    validation: dict[str, Any]
    findings: dict[str, Any]


def load_natural_trace_skew_config(path: str | Path) -> NaturalTraceSkewConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    base_dir = repository_root_for_config(config_path)
    config = NaturalTraceSkewConfig(
        output_dir=_resolve_path(raw["output_dir"], base_dir),
        trace_path=_resolve_path(raw["trace_path"], base_dir),
        max_read_requests=(
            int(raw["max_read_requests"])
            if raw.get("max_read_requests") is not None
            else None
        ),
        request_count_windows=tuple(int(value) for value in raw["request_count_windows"]),
        time_windows_s=tuple(float(value) for value in raw["time_windows_s"]),
        hotspot_work_share_threshold=float(raw["hotspot_work_share_threshold"]),
        primary_count_window=int(raw["primary_count_window"]),
        primary_time_window_s=float(raw["primary_time_window_s"]),
        heatmap_placement=str(raw["heatmap_placement"]),
        validation_sample_windows=int(raw["validation_sample_windows"]),
        stripe_bytes=int(raw["stripe_bytes"]),
        platter_count=int(raw["platter_count"]),
        placements=tuple(NaturalPlacementConfig(**value) for value in raw["placements"]),
        geometry=PanelGeometryConfig(**raw["geometry"]),
        movement=PanelMovementConfig(**raw["movement"]),
        timing=PanelTimingConfig(**raw["timing"]),
    )
    config.validate()
    return config


def run_natural_trace_skew_study(config: NaturalTraceSkewConfig) -> NaturalTraceSkewResult:
    trace_requests, load_stats = load_sorted_read_requests(
        config.trace_path,
        config.max_read_requests,
    )
    min_stripe = min(request.offset // config.stripe_bytes for request in trace_requests)
    max_stripe = max(request.offset // config.stripe_bytes for request in trace_requests)
    source_stats = {
        **load_stats,
        "trace_path": portable_path(config.trace_path),
        "trace_bytes": sum(request.size_bytes for request in trace_requests),
        "request_signature_sha256": trace_request_signature(trace_requests),
        "min_stripe_id": min_stripe,
        "max_stripe_id": max_stripe,
        "zone_count": config.zone_count,
        "balanced_zone_share": 1 / config.zone_count,
    }

    window_rows: list[dict[str, Any]] = []
    zone_rows: list[dict[str, Any]] = []
    validation_rows: list[dict[str, Any]] = []
    source_request_count = len(trace_requests)
    source_bytes = source_stats["trace_bytes"]

    for placement in config.placements:
        mapped = map_trace_requests(
            config,
            trace_requests,
            placement,
            min_stripe,
            max_stripe,
        )
        for window_size in config.request_count_windows:
            for window_index, requests in count_windows(mapped, window_size):
                computation = summarize_window(
                    config,
                    placement,
                    "request_count",
                    float(window_size),
                    window_index,
                    requests,
                    residual=len(requests) < window_size / 2,
                )
                window_rows.append(computation.row)
                if _keep_zone_detail(config, placement, "request_count", float(window_size)):
                    zone_rows.extend(_zone_detail_rows(computation))
        for window_s in config.time_windows_s:
            for window_index, requests in time_windows(mapped, window_s):
                computation = summarize_window(
                    config,
                    placement,
                    "time",
                    window_s,
                    window_index,
                    requests,
                    residual=False,
                )
                window_rows.append(computation.row)
                if _keep_zone_detail(config, placement, "time", window_s):
                    zone_rows.extend(_zone_detail_rows(computation))
        validation_rows.extend(
            validate_work_estimator(config, placement, mapped)
        )

    placement_rows = aggregate_placement_rows(
        window_rows,
        config.hotspot_work_share_threshold,
    )
    family_rows = aggregate_family_rows(placement_rows)
    invariants = validate_window_invariants(
        config,
        window_rows,
        source_request_count,
        source_bytes,
    )
    estimator_summary = summarize_estimator_validation(validation_rows)
    validation = {
        "passed": invariants["passed"] and estimator_summary["passed"],
        "window_invariants": invariants,
        "work_estimator": estimator_summary,
        "sample_rows": validation_rows,
    }
    if not validation["passed"]:
        raise RuntimeError(f"natural-skew validation failed: {validation}")
    findings = build_findings(config, source_stats, family_rows, validation)
    return NaturalTraceSkewResult(
        source_stats=source_stats,
        window_rows=window_rows,
        placement_rows=placement_rows,
        family_rows=family_rows,
        zone_rows=zone_rows,
        validation=validation,
        findings=findings,
    )


def load_sorted_read_requests(
    trace_path: Path,
    max_read_requests: int | None,
) -> tuple[list[TraceRequest], dict[str, Any]]:
    requests: list[TraceRequest] = []
    previous_arrival: float | None = None
    out_of_order_pairs = 0
    for request in iter_trace(trace_path):
        if request.io_type != "R":
            continue
        if previous_arrival is not None and request.arrival_s < previous_arrival:
            out_of_order_pairs += 1
        previous_arrival = request.arrival_s
        requests.append(request)
        if max_read_requests is not None and len(requests) >= max_read_requests:
            break
    if not requests:
        raise ValueError("trace contains no read requests")
    requests.sort(key=lambda request: (request.arrival_s, request.index))
    first_arrival = requests[0].arrival_s
    normalized = [replace(request, arrival_s=request.arrival_s - first_arrival) for request in requests]
    return normalized, {
        "read_requests": len(normalized),
        "trace_span_s": normalized[-1].arrival_s,
        "raw_out_of_order_adjacent_pairs": out_of_order_pairs,
        "timestamp_order_normalized": True,
    }


def map_trace_requests(
    config: NaturalTraceSkewConfig,
    requests: list[TraceRequest],
    placement: NaturalPlacementConfig,
    min_stripe: int,
    max_stripe: int,
) -> list[MappedNaturalRequest]:
    mapped: list[MappedNaturalRequest] = []
    zone_capacity = config.geometry.zone_height_racks * config.geometry.slots_per_half
    stripe_distance = max_stripe - min_stripe
    for request in requests:
        stripe_id = request.offset // config.stripe_bytes
        if placement.mode == "hash":
            platter_id = _hash_u64(stripe_id ^ int(placement.hash_seed)) % config.platter_count
        else:
            platter_id = (
                (stripe_id - min_stripe) * (config.platter_count - 1) // stripe_distance
                if stripe_distance
                else 0
            )
        zone_id, local_platter = divmod(platter_id, zone_capacity)
        local_level, slot = divmod(local_platter, config.geometry.slots_per_half)
        mapped.append(
            MappedNaturalRequest(
                source_index=request.index,
                arrival_s=request.arrival_s,
                size_bytes=request.size_bytes,
                platter_id=platter_id,
                zone_id=zone_id,
                local_level=local_level,
                slot_in_half=slot,
            )
        )
    return mapped


def count_windows(
    requests: list[MappedNaturalRequest],
    window_size: int,
) -> Iterable[tuple[int, list[MappedNaturalRequest]]]:
    for start in range(0, len(requests), window_size):
        yield start // window_size, requests[start : start + window_size]


def time_windows(
    requests: list[MappedNaturalRequest],
    window_s: float,
) -> Iterable[tuple[int, list[MappedNaturalRequest]]]:
    current_index: int | None = None
    current: list[MappedNaturalRequest] = []
    for request in requests:
        index = int(math.floor(request.arrival_s / window_s))
        if current_index is None:
            current_index = index
        if index != current_index:
            yield current_index, current
            current_index = index
            current = []
        current.append(request)
    if current_index is not None and current:
        yield current_index, current


def summarize_window(
    config: NaturalTraceSkewConfig,
    placement: NaturalPlacementConfig,
    window_kind: str,
    window_size: float,
    window_index: int,
    requests: list[MappedNaturalRequest],
    residual: bool,
) -> WindowComputation:
    zone_logical = [0] * config.zone_count
    zone_bytes = [0] * config.zone_count
    merged: dict[int, list[int]] = {}
    for request in requests:
        zone_logical[request.zone_id] += 1
        zone_bytes[request.zone_id] += request.size_bytes
        current = merged.get(request.platter_id)
        if current is None:
            merged[request.platter_id] = [request.size_bytes, 1]
        else:
            current[0] += request.size_bytes
            current[1] += 1

    zone_tasks = [0] * config.zone_count
    zone_work = [0.0] * config.zone_count
    zone_capacity = config.geometry.zone_height_racks * config.geometry.slots_per_half
    for platter_id, (size_bytes, _) in merged.items():
        zone_id, local_platter = divmod(platter_id, zone_capacity)
        local_level, slot = divmod(local_platter, config.geometry.slots_per_half)
        zone_tasks[zone_id] += 1
        zone_work[zone_id] += estimate_service_work_s(
            config,
            zone_id,
            local_level,
            slot,
            size_bytes,
        )

    logical_total = len(requests)
    byte_total = sum(zone_bytes)
    task_total = len(merged)
    work_total = sum(zone_work)
    max_work = max(zone_work, default=0.0)
    critical_work_zone = zone_work.index(max_work) if zone_work else -1
    max_logical = max(zone_logical, default=0)
    max_tasks = max(zone_tasks, default=0)
    max_bytes = max(zone_bytes, default=0)
    if window_kind == "request_count":
        start_s = requests[0].arrival_s if requests else 0.0
        end_s = requests[-1].arrival_s if requests else start_s
    else:
        start_s = window_index * window_size
        end_s = (window_index + 1) * window_size
    capacity = work_total / (config.zone_count * max_work) if max_work else 1.0
    row = {
        "placement": placement.name,
        "placement_display_name": placement.display_name,
        "placement_family": placement.family,
        "window_kind": window_kind,
        "window_size": window_size,
        "window_index": window_index,
        "window_start_s": start_s,
        "window_end_s": end_s,
        "window_duration_s": max(0.0, end_s - start_s),
        "is_residual": residual,
        "logical_request_count": logical_total,
        "logical_bytes": byte_total,
        "physical_task_count": task_total,
        "requests_per_physical_task": logical_total / task_total if task_total else 0.0,
        "critical_logical_zone": zone_logical.index(max_logical) if zone_logical else -1,
        "critical_work_zone": critical_work_zone,
        "max_zone_logical_share": max_logical / logical_total if logical_total else 0.0,
        "max_zone_byte_share": max_bytes / byte_total if byte_total else 0.0,
        "max_zone_task_share": max_tasks / task_total if task_total else 0.0,
        "max_zone_work_share": max_work / work_total if work_total else 0.0,
        "work_max_mean_ratio": max_work / (work_total / config.zone_count) if work_total else 1.0,
        "work_jain_fairness": _jain_fairness(zone_work),
        "static_capacity_efficiency_proxy": capacity,
        "stranded_capacity_share_proxy": 1.0 - capacity,
    }
    return WindowComputation(
        row=row,
        zone_logical_counts=tuple(zone_logical),
        zone_task_counts=tuple(zone_tasks),
        zone_work_s=tuple(zone_work),
    )


def estimate_service_work_s(
    config: NaturalTraceSkewConfig,
    zone_id: int,
    local_level: int,
    slot_in_half: int,
    size_bytes: int,
) -> float:
    row_id, side = divmod(zone_id, 2)
    reader_local_level = config.geometry.zone_height_racks // 2
    reader_slot = 0 if side == 0 else config.geometry.slots_per_half - 1
    vertical_levels = abs(local_level - reader_local_level)
    vertical_s = vertical_levels * config.movement.vertical_s_per_level
    slot_width_m = config.geometry.half_panel_length_m / (config.geometry.slots_per_half - 1)
    horizontal_m = abs(slot_in_half - reader_slot) * slot_width_m
    one_way_s = vertical_s + _horizontal_time_s(config.movement, horizontal_m)
    fixed_s = (
        config.timing.storage_pick_s
        + config.timing.reader_load_s
        + config.timing.reader_unload_s
        + config.timing.storage_place_s
    )
    read_s = (
        config.timing.reader_mount_s
        + config.timing.reader_base_s
        + (size_bytes / MIB) / config.timing.reader_mib_per_s
    )
    return 2.0 * one_way_s + fixed_s + read_s


def aggregate_placement_rows(
    rows: list[dict[str, Any]],
    hotspot_threshold: float,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, float], list[dict[str, Any]]] = {}
    for row in rows:
        key = (row["placement"], row["window_kind"], float(row["window_size"]))
        groups.setdefault(key, []).append(row)
    result: list[dict[str, Any]] = []
    for key, group in sorted(groups.items()):
        ordered = sorted(group, key=lambda row: row["window_index"])
        eligible = [row for row in ordered if not row["is_residual"]]
        work_shares = sorted(float(row["max_zone_work_share"]) for row in eligible)
        logical_shares = sorted(float(row["max_zone_logical_share"]) for row in eligible)
        task_shares = sorted(float(row["max_zone_task_share"]) for row in eligible)
        capacities = sorted(float(row["static_capacity_efficiency_proxy"]) for row in eligible)
        hot_runs = _hotspot_runs(eligible, hotspot_threshold)
        switches = sum(
            first["critical_work_zone"] != second["critical_work_zone"]
            for first, second in zip(eligible, eligible[1:])
        )
        result.append(
            {
                "placement": key[0],
                "placement_display_name": eligible[0]["placement_display_name"],
                "placement_family": eligible[0]["placement_family"],
                "window_kind": key[1],
                "window_size": key[2],
                "window_count": len(eligible),
                "mean_requests_per_window": mean(float(row["logical_request_count"]) for row in eligible),
                "logical_share_p50": _percentile(logical_shares, 0.50),
                "logical_share_p95": _percentile(logical_shares, 0.95),
                "work_share_p50": _percentile(work_shares, 0.50),
                "work_share_p95": _percentile(work_shares, 0.95),
                "work_share_max": max(work_shares),
                "task_share_p95": _percentile(task_shares, 0.95),
                "work_jain_fairness_mean": mean(float(row["work_jain_fairness"]) for row in eligible),
                "capacity_proxy_mean": mean(capacities),
                "capacity_proxy_p05": _percentile(capacities, 0.05),
                "hot_window_fraction": mean(
                    float(row["max_zone_work_share"] >= hotspot_threshold) for row in eligible
                ),
                "severe_window_fraction": mean(
                    float(row["max_zone_work_share"] >= 0.40) for row in eligible
                ),
                "critical_zone_switch_rate": switches / (len(eligible) - 1)
                if len(eligible) > 1
                else 0.0,
                "hotspot_run_windows_p95": _percentile(sorted(hot_runs), 0.95) if hot_runs else 0.0,
                "requests_per_physical_task_mean": mean(
                    float(row["requests_per_physical_task"]) for row in eligible
                ),
            }
        )
    return result


def aggregate_family_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, float], list[dict[str, Any]]] = {}
    for row in rows:
        key = (row["placement_family"], row["window_kind"], float(row["window_size"]))
        groups.setdefault(key, []).append(row)
    identity = {
        "placement",
        "placement_display_name",
        "placement_family",
        "window_kind",
        "window_size",
    }
    result: list[dict[str, Any]] = []
    for key, group in sorted(groups.items()):
        aggregate: dict[str, Any] = {
            "placement_family": key[0],
            "window_kind": key[1],
            "window_size": key[2],
            "placement_count": len(group),
        }
        for field in group[0]:
            if field in identity:
                continue
            values = [float(row[field]) for row in group]
            aggregate[f"{field}_mean"] = mean(values)
            aggregate[f"{field}_std"] = pstdev(values) if len(values) > 1 else 0.0
            aggregate[f"{field}_min"] = min(values)
            aggregate[f"{field}_max"] = max(values)
        result.append(aggregate)
    return result


def validate_window_invariants(
    config: NaturalTraceSkewConfig,
    rows: list[dict[str, Any]],
    source_request_count: int,
    source_bytes: int,
) -> dict[str, Any]:
    groups: dict[tuple[str, str, float], list[dict[str, Any]]] = {}
    for row in rows:
        key = (row["placement"], row["window_kind"], float(row["window_size"]))
        groups.setdefault(key, []).append(row)
    failures: list[str] = []
    for key, group in groups.items():
        request_count = sum(int(row["logical_request_count"]) for row in group)
        byte_count = sum(int(row["logical_bytes"]) for row in group)
        if request_count != source_request_count:
            failures.append(f"{key} request count {request_count} != {source_request_count}")
        if byte_count != source_bytes:
            failures.append(f"{key} bytes {byte_count} != {source_bytes}")
        if any(int(row["physical_task_count"]) > int(row["logical_request_count"]) for row in group):
            failures.append(f"{key} has more physical tasks than logical requests")
        if any(
            not 1 / config.zone_count - 1e-12 <= float(row["max_zone_work_share"]) <= 1.0
            for row in group
        ):
            failures.append(f"{key} has an invalid work share")
    return {
        "passed": not failures,
        "checked_window_configurations": len(groups),
        "failures": failures,
    }


def validate_work_estimator(
    config: NaturalTraceSkewConfig,
    placement: NaturalPlacementConfig,
    requests: list[MappedNaturalRequest],
) -> list[dict[str, Any]]:
    complete_windows = len(requests) // config.primary_count_window
    sample_count = min(config.validation_sample_windows, complete_windows)
    indices = _evenly_spaced_indices(complete_windows, sample_count)
    rows: list[dict[str, Any]] = []
    for window_index in indices:
        start = window_index * config.primary_count_window
        window = requests[start : start + config.primary_count_window]
        predicted = summarize_window(
            config,
            placement,
            "request_count",
            float(config.primary_count_window),
            window_index,
            window,
            residual=False,
        )
        simulator = PanelStaticZoneSimulator(_panel_config(config, f"validation-{placement.name}"))
        panel_requests = [
            simulator.make_request(
                request_index=request.source_index,
                zone_id=request.zone_id,
                local_level=request.local_level,
                slot_in_half=request.slot_in_half,
                size_bytes=request.size_bytes,
            )
            for request in window
        ]
        merged = merge_panel_requests(panel_requests)
        exact = simulator.run(merged)
        exact_work = [0.0] * config.zone_count
        for detail in exact.details:
            exact_work[detail.zone_id] += detail.cycle_s
        exact_total = sum(exact_work)
        exact_share = max(exact_work) / exact_total if exact_total else 0.0
        predicted_share = float(predicted.row["max_zone_work_share"])
        rows.append(
            {
                "placement": placement.name,
                "window_index": window_index,
                "logical_requests": len(window),
                "predicted_physical_tasks": predicted.row["physical_task_count"],
                "exact_physical_tasks": len(merged),
                "predicted_max_zone_work_share": predicted_share,
                "exact_max_zone_work_share": exact_share,
                "absolute_error": abs(predicted_share - exact_share),
            }
        )
    return rows


def summarize_estimator_validation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    errors = [float(row["absolute_error"]) for row in rows]
    task_count_matches = all(
        int(row["predicted_physical_tasks"]) == int(row["exact_physical_tasks"])
        for row in rows
    )
    mean_error = mean(errors) if errors else 0.0
    max_error = max(errors, default=0.0)
    return {
        "passed": task_count_matches and mean_error <= 0.03 and max_error <= 0.08,
        "sample_count": len(rows),
        "physical_task_counts_match": task_count_matches,
        "mean_absolute_share_error": mean_error,
        "max_absolute_share_error": max_error,
        "acceptance": "mean error <= 0.03, max error <= 0.08, exact merge cardinality",
    }


def build_findings(
    config: NaturalTraceSkewConfig,
    source_stats: dict[str, Any],
    family_rows: list[dict[str, Any]],
    validation: dict[str, Any],
) -> dict[str, Any]:
    def row(family: str, kind: str, size: float) -> dict[str, Any]:
        return next(
            value
            for value in family_rows
            if value["placement_family"] == family
            and value["window_kind"] == kind
            and math.isclose(float(value["window_size"]), size)
        )

    random_small = row("randomized_hash", "request_count", float(min(config.request_count_windows)))
    random_primary = row("randomized_hash", "request_count", float(config.primary_count_window))
    random_large = row("randomized_hash", "request_count", float(max(config.request_count_windows)))
    random_time = row("randomized_hash", "time", config.primary_time_window_s)
    contiguous_primary = row("contiguous_lba", "request_count", float(config.primary_count_window))
    short_burst = random_small["work_share_p95_mean"] >= config.hotspot_work_share_threshold
    sustained_randomized = (
        random_primary["work_share_p95_mean"] >= config.hotspot_work_share_threshold
        or random_time["work_share_p95_mean"] >= config.hotspot_work_share_threshold
    )
    placement_correlated = (
        contiguous_primary["work_share_p95_mean"] >= config.hotspot_work_share_threshold
    )
    if sustained_randomized:
        classification = "sustained_under_randomized_placement"
    elif short_burst and placement_correlated:
        classification = "short_burst_and_placement_correlated"
    elif short_burst:
        classification = "short_burst_only"
    elif placement_correlated:
        classification = "placement_correlated_only"
    else:
        classification = "weak_at_measured_scales"
    return {
        "scope": {
            "read_requests": source_stats["read_requests"],
            "trace_span_s": source_stats["trace_span_s"],
            "natural_timestamp_order": True,
            "artificial_request_reordering": False,
        },
        "randomized_placement": {
            "smallest_count_window": min(config.request_count_windows),
            "smallest_work_share_p95": random_small["work_share_p95_mean"],
            "primary_count_window": config.primary_count_window,
            "primary_work_share_p95": random_primary["work_share_p95_mean"],
            "primary_hot_window_fraction": random_primary["hot_window_fraction_mean"],
            "largest_count_window": max(config.request_count_windows),
            "largest_work_share_p95": random_large["work_share_p95_mean"],
            "primary_time_window_s": config.primary_time_window_s,
            "time_work_share_p95": random_time["work_share_p95_mean"],
        },
        "placement_sensitivity": {
            "primary_randomized_work_share_p95": random_primary["work_share_p95_mean"],
            "primary_contiguous_work_share_p95": contiguous_primary["work_share_p95_mean"],
        },
        "rq1_interpretation": {
            "classification": classification,
            "short_burst_above_threshold": short_burst,
            "sustained_randomized_above_threshold": sustained_randomized,
            "placement_correlated_above_threshold": placement_correlated,
            "threshold": config.hotspot_work_share_threshold,
        },
        "validation": validation,
    }


def write_natural_trace_skew_outputs(
    config: NaturalTraceSkewConfig,
    study: NaturalTraceSkewResult,
) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    _write_rows(config.output_dir / "window_detail.csv", study.window_rows)
    _write_rows(config.output_dir / "placement_summary.csv", study.placement_rows)
    _write_rows(config.output_dir / "family_summary.csv", study.family_rows)
    _write_rows(config.output_dir / "zone_detail.csv", study.zone_rows)
    _write_rows(config.output_dir / "validation_samples.csv", study.validation["sample_rows"])
    (config.output_dir / "config.json").write_text(
        json.dumps(config.to_json_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    (config.output_dir / "summary.json").write_text(
        json.dumps(
            {
                "source": study.source_stats,
                "findings": study.findings,
                "validation": {
                    key: value
                    for key, value in study.validation.items()
                    if key != "sample_rows"
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_analysis(config, study, config.output_dir / "RQ1_NATURAL_TRACE_CHARACTERIZATION.md")
    figures_dir = config.output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    write_natural_trace_skew_figures(config, study, figures_dir)


def write_natural_trace_skew_figures(
    config: NaturalTraceSkewConfig,
    study: NaturalTraceSkewResult,
    output_dir: Path,
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(Path("results/.mplconfig").resolve()))
    os.environ.setdefault("XDG_CACHE_HOME", str(Path("results/.cache").resolve()))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

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
    _plot_skew_vs_window(config, study.family_rows, output_dir, plt)
    _plot_logical_vs_work(config, study.family_rows, output_dir, plt)
    _plot_zone_heatmaps(config, study.zone_rows, output_dir, plt, np)
    _plot_capacity_and_hot_fraction(config, study.family_rows, output_dir, plt)
    _plot_placement_sensitivity(config, study.placement_rows, output_dir, plt)


def _plot_skew_vs_window(config, rows, output_dir, plt) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(9.7, 3.8))
    for ax, kind, title, xlabel in [
        (axes[0], "request_count", "A. Request-count windows", "Requests per window"),
        (axes[1], "time", "B. Time windows", "Window duration (s)"),
    ]:
        for family, color, label in [
            ("randomized_hash", "#2F6B9A", "Randomized placement"),
            ("contiguous_lba", "#D9822B", "Contiguous-LBA sensitivity"),
        ]:
            series = sorted(
                (row for row in rows if row["placement_family"] == family and row["window_kind"] == kind),
                key=lambda row: row["window_size"],
            )
            x = [row["window_size"] for row in series]
            y = [row["work_share_p95_mean"] * 100 for row in series]
            ax.plot(x, y, color=color, marker="o", linewidth=2, label=label)
            if family == "randomized_hash":
                lower = [row["work_share_p95_min"] * 100 for row in series]
                upper = [row["work_share_p95_max"] * 100 for row in series]
                ax.fill_between(x, lower, upper, color=color, alpha=0.16, linewidth=0)
        ax.axhline(100 / config.zone_count, color="#667085", linestyle=":", linewidth=1.2)
        ax.set_xscale("log")
        ax.set_xlabel(xlabel)
        ax.set_ylabel("P95 busiest-zone post-merge work (%)")
        ax.set_title(title)
        _style(ax)
    axes[0].legend(frameon=False)
    fig.suptitle("Natural skew sensitivity to observation scale", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    _save(fig, output_dir, "fig1_natural_skew_vs_window", tight=False)


def _plot_logical_vs_work(config, rows, output_dir, plt) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(9.7, 4.2))
    for ax, kind, title, xlabel in [
        (axes[0], "request_count", "A. Request-count windows", "Requests per window"),
        (axes[1], "time", "B. Time windows", "Window duration (s)"),
    ]:
        series = sorted(
            (
                row
                for row in rows
                if row["placement_family"] == "randomized_hash" and row["window_kind"] == kind
            ),
            key=lambda row: row["window_size"],
        )
        x = [row["window_size"] for row in series]
        ax.plot(x, [row["logical_share_p95_mean"] * 100 for row in series], color="#2F6B9A", marker="o", linewidth=2, label="Logical requests")
        ax.plot(x, [row["work_share_p95_mean"] * 100 for row in series], color="#C84C4C", marker="s", linewidth=2, label="Post-merge work")
        ax.axhline(100 / config.zone_count, color="#667085", linestyle=":", linewidth=1.2)
        ax.set_xscale("log")
        ax.set_xlabel(xlabel)
        ax.set_ylabel("P95 busiest-zone share (%)")
        ax.set_title(title)
        _style(ax)
    axes[0].legend(frameon=False)
    fig.suptitle("Merge changes request skew into physical service demand", fontsize=12, y=0.98)
    fig.tight_layout(rect=(0, 0.04, 1, 0.91))
    _save(fig, output_dir, "fig2_logical_vs_post_merge_work", tight=False)


def _plot_zone_heatmaps(config, rows, output_dir, plt, np) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(9.8, 5.9), constrained_layout=True)
    settings = [
        ("request_count", float(config.primary_count_window), f"A. {config.primary_count_window:,}-request windows"),
        ("time", config.primary_time_window_s, f"B. {config.primary_time_window_s:g}-second windows"),
    ]
    image = None
    for ax, (kind, size, title) in zip(axes, settings):
        subset = [
            row
            for row in rows
            if row["window_kind"] == kind and math.isclose(float(row["window_size"]), size)
        ]
        window_ids = sorted({int(row["window_index"]) for row in subset})
        lookup = {(int(row["zone_id"]), int(row["window_index"])): float(row["zone_work_share"]) * 100 for row in subset}
        matrix = np.array(
            [
                [lookup.get((zone, window), 0.0) for window in window_ids]
                for zone in range(config.zone_count)
            ]
        )
        image = ax.imshow(matrix, aspect="auto", cmap="YlOrRd", vmin=0, vmax=max(30, matrix.max()))
        ax.set_ylabel("Static zone")
        ax.set_yticks(range(config.zone_count))
        ax.set_title(title)
        if kind == "time":
            tick_positions = np.linspace(0, max(0, len(window_ids) - 1), min(7, len(window_ids)), dtype=int)
            ax.set_xticks(tick_positions, [f"{window_ids[index] * size / 60:.0f}" for index in tick_positions])
            ax.set_xlabel("Trace time (min)")
        else:
            ax.set_xlabel("Natural-order window index")
    if image is not None:
        fig.colorbar(image, ax=axes, label="Zone share of post-merge work (%)", shrink=0.86)
    fig.suptitle(f"Natural zone activity under {config.heatmap_placement}", fontsize=12)
    _save(fig, output_dir, "fig3_natural_zone_activity_heatmap", tight=False)


def _plot_capacity_and_hot_fraction(config, rows, output_dir, plt) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(9.7, 3.8))
    for family, color, label in [
        ("randomized_hash", "#2F6B9A", "Randomized placement"),
        ("contiguous_lba", "#D9822B", "Contiguous-LBA sensitivity"),
    ]:
        series = sorted(
            (row for row in rows if row["placement_family"] == family and row["window_kind"] == "request_count"),
            key=lambda row: row["window_size"],
        )
        x = [row["window_size"] for row in series]
        axes[0].plot(x, [row["capacity_proxy_mean_mean"] * 100 for row in series], color=color, marker="o", linewidth=2, label=label)
        axes[1].plot(x, [row["hot_window_fraction_mean"] * 100 for row in series], color=color, marker="o", linewidth=2, label=label)
    for ax in axes:
        ax.set_xscale("log")
        ax.set_xlabel("Requests per window")
        _style(ax)
    axes[0].set_ylabel("Mean static-capacity proxy (%)")
    axes[0].set_title("A. Potential capacity available to fixed owners")
    axes[1].set_ylabel(f"Windows above {config.hotspot_work_share_threshold * 100:.0f}% work share (%)")
    axes[1].set_title("B. Frequency of naturally hot windows")
    axes[0].legend(frameon=False)
    _save(fig, output_dir, "fig4_capacity_and_hotspot_frequency")


def _plot_placement_sensitivity(config, rows, output_dir, plt) -> None:
    settings = [
        ("request_count", float(config.primary_count_window), f"{config.primary_count_window:,} requests"),
        ("time", config.primary_time_window_s, f"{config.primary_time_window_s:g} seconds"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.7))
    placement_order = {
        placement.name: index for index, placement in enumerate(config.placements)
    }
    for ax, (kind, size, title) in zip(axes, settings):
        subset = sorted(
            (
                row
                for row in rows
                if row["window_kind"] == kind
                and math.isclose(float(row["window_size"]), size)
            ),
            key=lambda row: placement_order[row["placement"]],
        )
        labels = [row["placement_display_name"] for row in subset]
        colors = ["#2F6B9A" if row["placement_family"] == "randomized_hash" else "#D9822B" for row in subset]
        ax.bar(labels, [row["work_share_p95"] * 100 for row in subset], color=colors)
        ax.axhline(100 / config.zone_count, color="#667085", linestyle=":", linewidth=1.2)
        ax.set_ylabel("P95 busiest-zone post-merge work (%)")
        ax.set_title(title)
        ax.tick_params(axis="x", rotation=18)
        _style(ax)
    fig.suptitle("Zone-level skew depends on the placement assumption", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    _save(fig, output_dir, "fig5_placement_sensitivity", tight=False)


def _write_analysis(
    config: NaturalTraceSkewConfig,
    study: NaturalTraceSkewResult,
    path: Path,
) -> None:
    random = study.findings["randomized_placement"]
    sensitivity = study.findings["placement_sensitivity"]
    interpretation = study.findings["rq1_interpretation"]
    estimator = study.validation["work_estimator"]
    lines = [
        "# RQ1: Natural Trace Skew Characterization",
        "",
        "## Research question",
        "",
        "> In natural timestamp order, does post-merge physical service demand remain spatially skewed at realistic request-count and time scales?",
        "",
        "## Experiment contract",
        "",
        f"- Source trace: `{portable_path(config.trace_path)}`.",
        f"- Reads: {study.source_stats['read_requests']:,} over {study.source_stats['trace_span_s'] / 60:.1f} minutes.",
        "- Request order: original timestamps after explicitly sorting the raw file; no artificial hot-zone reordering.",
        f"- Count windows: {', '.join(f'{value:,}' for value in config.request_count_windows)} requests.",
        f"- Time windows: {', '.join(f'{value:g}s' for value in config.time_windows_s)}.",
        "- Merge scope: independently within every measured window; repeated accesses to one mapped platter become one physical service with summed bytes.",
        "- Work metric: estimated local platter-to-reader round trip, fixed pick/load/unload/place time, and reader transfer time. Inter-task repositioning is omitted from the characterization proxy.",
        "",
        "## Placement assumptions",
        "",
        "The trace contains LUN offsets, not the real mapping from data to Silica platters and zones. Results are therefore reported under two explicit assumptions:",
        "",
        "1. `Randomized hash`: three stable hash seeds distribute 64 MiB stripes across 6,400 panel positions. This matches a no-placement-locality assumption and reports seed variation.",
        "2. `Contiguous LBA`: logical block ranges map contiguously across the panel. This is a sensitivity bound, not a claim about the deployed Silica placement.",
        "",
        "## Primary findings",
        "",
        f"Under randomized placement, the P95 busiest-zone post-merge work share is {random['smallest_work_share_p95'] * 100:.1f}% for {random['smallest_count_window']:,}-request windows, {random['primary_work_share_p95'] * 100:.1f}% for {random['primary_count_window']:,}-request windows, and {random['largest_work_share_p95'] * 100:.1f}% for {random['largest_count_window']:,}-request windows.",
        f"At the primary {random['primary_count_window']:,}-request scale, {random['primary_hot_window_fraction'] * 100:.1f}% of windows exceed the configured {config.hotspot_work_share_threshold * 100:.0f}% work-share threshold.",
        f"For {random['primary_time_window_s'] / 60:.1f}-minute windows, the randomized-placement P95 busiest-zone work share is {random['time_work_share_p95'] * 100:.1f}%.",
        f"At {config.primary_count_window:,} requests, placement changes the P95 result from {sensitivity['primary_randomized_work_share_p95'] * 100:.1f}% under randomized hashing to {sensitivity['primary_contiguous_work_share_p95'] * 100:.1f}% under contiguous-LBA mapping.",
        "",
        "## RQ1 interpretation",
        "",
        f"Classification: `{interpretation['classification']}`.",
        "",
        "The trace supports a short-timescale burst problem under randomized placement, but it does not support a claim of severe persistent imbalance at the primary 5,000-request or 60-second scales. Stronger long-lived skew appears only when LBA locality is preserved by the placement assumption. The defensible motivation is therefore conditional: adaptation must react quickly to bursts, or exploit observed placement-access correlation; static zones are not shown to be universally imbalanced.",
        "",
        "## Validation",
        "",
        f"- Window conservation checks: {study.validation['window_invariants']['checked_window_configurations']} placement/window configurations passed exact logical-request and byte conservation.",
        f"- Merge cardinality: {'passed' if estimator['physical_task_counts_match'] else 'failed'} against the existing batch-wide merge implementation.",
        f"- Work-share proxy versus full static-zone simulation: mean absolute error {estimator['mean_absolute_share_error'] * 100:.2f} percentage points; maximum {estimator['max_absolute_share_error'] * 100:.2f} points across {estimator['sample_count']} sampled windows.",
        "",
        "## Evidence boundary",
        "",
        "- This is one one-hour LUN trace, not a multi-dataset production prevalence study.",
        "- Zone-level skew is conditional on synthetic placement because the trace does not expose real platter placement.",
        "- Larger windows have fewer samples; P95 values at the longest time scales are descriptive rather than statistically stable.",
        "- Empty time buckets are excluded; reported time-window distributions characterize periods containing read activity.",
        "- The capacity metric is a fixed-owner work-balance proxy, not an online throughput prediction.",
        "- The study characterizes natural demand; it does not yet model Microsoft work stealing or the proposed adaptive policy.",
        "",
        "## Decision rule for the research story",
        "",
        "- If randomized-placement post-merge skew remains high across realistic scales, proceed with natural static-stranding and work-stealing experiments.",
        "- If skew appears only at short scales, frame the problem as burst/tail adaptation and make control-epoch duration central.",
        "- If skew is low under randomized placement but high only under contiguous placement, the motivation is placement-correlated access, not universal trace skew.",
        "",
        "## Figure guide",
        "",
        "- `fig1_natural_skew_vs_window`: P95 post-merge work skew versus count/time scale.",
        "- `fig2_logical_vs_post_merge_work`: logical request skew versus physical service-demand skew.",
        "- `fig3_natural_zone_activity_heatmap`: zone activity over natural trace order.",
        "- `fig4_capacity_and_hotspot_frequency`: fixed-owner capacity proxy and hot-window frequency.",
        "- `fig5_placement_sensitivity`: sensitivity to the unavailable platter-placement mapping.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _keep_zone_detail(
    config: NaturalTraceSkewConfig,
    placement: NaturalPlacementConfig,
    window_kind: str,
    window_size: float,
) -> bool:
    if placement.name != config.heatmap_placement:
        return False
    return (
        window_kind == "request_count"
        and math.isclose(window_size, float(config.primary_count_window))
    ) or (
        window_kind == "time"
        and math.isclose(window_size, config.primary_time_window_s)
    )


def _zone_detail_rows(computation: WindowComputation) -> list[dict[str, Any]]:
    total_work = sum(computation.zone_work_s)
    return [
        {
            "placement": computation.row["placement"],
            "window_kind": computation.row["window_kind"],
            "window_size": computation.row["window_size"],
            "window_index": computation.row["window_index"],
            "zone_id": zone,
            "logical_requests": computation.zone_logical_counts[zone],
            "physical_tasks": computation.zone_task_counts[zone],
            "estimated_work_s": computation.zone_work_s[zone],
            "zone_work_share": computation.zone_work_s[zone] / total_work if total_work else 0.0,
        }
        for zone in range(len(computation.zone_work_s))
    ]


def _panel_config(config: NaturalTraceSkewConfig, name: str) -> PanelStaticZoneConfig:
    return PanelStaticZoneConfig(
        output_dir=config.output_dir / "validation" / name,
        seed=0,
        geometry=config.geometry,
        movement=config.movement,
        timing=config.timing,
        workload=PanelWorkloadConfig(
            batch_size=config.primary_count_window,
            request_size_bytes=1,
            request_merge=True,
        ),
    )


def _hotspot_runs(rows: list[dict[str, Any]], threshold: float) -> list[int]:
    runs: list[int] = []
    current_zone: int | None = None
    current_length = 0
    previous_index: int | None = None
    for row in rows:
        hot = float(row["max_zone_work_share"]) >= threshold
        zone = int(row["critical_work_zone"])
        index = int(row["window_index"])
        consecutive = previous_index is not None and index == previous_index + 1
        if hot and zone == current_zone and consecutive:
            current_length += 1
        else:
            if current_length:
                runs.append(current_length)
            current_zone = zone if hot else None
            current_length = 1 if hot else 0
        previous_index = index
    if current_length:
        runs.append(current_length)
    return runs


def _evenly_spaced_indices(total: int, count: int) -> list[int]:
    if count <= 0 or total <= 0:
        return []
    if count == 1:
        return [0]
    return sorted({round(index * (total - 1) / (count - 1)) for index in range(count)})


def trace_request_signature(requests: list[TraceRequest]) -> str:
    digest = hashlib.sha256()
    for request in requests:
        digest.update(
            f"{request.index}:{request.arrival_s:.9f}:{request.offset}:{request.size_bytes}\n".encode("ascii")
        )
    return digest.hexdigest()


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


def _save(fig, output_dir: Path, name: str, tight: bool = True) -> None:
    if tight:
        fig.tight_layout()
    fig.savefig(output_dir / f"{name}.pdf", bbox_inches="tight", facecolor="white")
    fig.savefig(output_dir / f"{name}.png", dpi=300, bbox_inches="tight", facecolor="white")
    import matplotlib.pyplot as plt

    plt.close(fig)
