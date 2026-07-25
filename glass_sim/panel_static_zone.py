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

from .paths import portable_path, repository_root_for_config


MIB = 1024 * 1024


@dataclass(frozen=True)
class PanelGeometryConfig:
    levels: int
    zone_height_racks: int
    half_panel_length_m: float
    slots_per_half: int
    glass_capacity_bytes: int

    def validate(self) -> None:
        if self.levels <= 0:
            raise ValueError("geometry.levels must be positive")
        if self.zone_height_racks <= 0:
            raise ValueError("geometry.zone_height_racks must be positive")
        if self.levels % self.zone_height_racks != 0:
            raise ValueError("geometry.levels must be divisible by geometry.zone_height_racks")
        if self.half_panel_length_m <= 0:
            raise ValueError("geometry.half_panel_length_m must be positive")
        if self.slots_per_half <= 1:
            raise ValueError("geometry.slots_per_half must be greater than 1")
        if self.glass_capacity_bytes <= 0:
            raise ValueError("geometry.glass_capacity_bytes must be positive")


@dataclass(frozen=True)
class PanelMovementConfig:
    horizontal_max_m_s: float
    horizontal_accel_m_s2: float
    horizontal_min_s: float
    vertical_s_per_level: float

    def validate(self) -> None:
        if self.horizontal_max_m_s <= 0:
            raise ValueError("movement.horizontal_max_m_s must be positive")
        if self.horizontal_accel_m_s2 <= 0:
            raise ValueError("movement.horizontal_accel_m_s2 must be positive")
        if self.horizontal_min_s < 0:
            raise ValueError("movement.horizontal_min_s cannot be negative")
        if self.vertical_s_per_level < 0:
            raise ValueError("movement.vertical_s_per_level cannot be negative")


@dataclass(frozen=True)
class PanelTimingConfig:
    storage_pick_s: float
    reader_load_s: float
    reader_unload_s: float
    storage_place_s: float
    reader_mount_s: float
    reader_base_s: float
    reader_mib_per_s: float

    def validate(self) -> None:
        for key, value in asdict(self).items():
            if value < 0:
                raise ValueError(f"timing.{key} cannot be negative")
        if self.reader_mib_per_s <= 0:
            raise ValueError("timing.reader_mib_per_s must be positive")


@dataclass(frozen=True)
class PanelWorkloadConfig:
    batch_size: int
    request_size_bytes: int
    placement: str = "uniform_round_robin"
    request_merge: bool = True
    hot_zone: int = 0
    hot_zone_fraction: float = 0.8
    hot_zone_width: int = 1

    def validate(self) -> None:
        if self.batch_size <= 0:
            raise ValueError("workload.batch_size must be positive")
        if self.request_size_bytes <= 0:
            raise ValueError("workload.request_size_bytes must be positive")
        if self.placement not in {"uniform_round_robin", "spatial_skew"}:
            raise ValueError("workload.placement must be 'uniform_round_robin' or 'spatial_skew'")
        if self.hot_zone < 0:
            raise ValueError("workload.hot_zone cannot be negative")
        if not 0.0 <= self.hot_zone_fraction <= 1.0:
            raise ValueError("workload.hot_zone_fraction must be between 0 and 1")
        if self.hot_zone_width <= 0:
            raise ValueError("workload.hot_zone_width must be positive")


@dataclass(frozen=True)
class PanelStaticZoneConfig:
    output_dir: Path
    seed: int
    geometry: PanelGeometryConfig
    movement: PanelMovementConfig
    timing: PanelTimingConfig
    workload: PanelWorkloadConfig

    def validate(self) -> None:
        self.geometry.validate()
        self.movement.validate()
        self.timing.validate()
        self.workload.validate()
        row_count = self.geometry.levels // self.geometry.zone_height_racks
        zone_count = row_count * 2
        if self.workload.hot_zone >= zone_count:
            raise ValueError("workload.hot_zone must be within the panel zone count")
        if self.workload.hot_zone_width > zone_count:
            raise ValueError("workload.hot_zone_width cannot exceed the panel zone count")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "output_dir": portable_path(self.output_dir),
            "seed": self.seed,
            "geometry": asdict(self.geometry),
            "movement": asdict(self.movement),
            "timing": asdict(self.timing),
            "workload": asdict(self.workload),
        }


@dataclass(frozen=True)
class PanelRequest:
    request_index: int
    arrival_s: float
    size_bytes: int
    platter_id: int
    zone_id: int
    row_id: int
    side: str
    level: int
    slot_in_half: int
    reader_level: int
    reader_slot_in_half: int
    merged_request_count: int = 1


@dataclass
class ZoneState:
    zone_id: int
    row_id: int
    side: str
    reader_level: int
    reader_slot_in_half: int
    shuttle_level: int
    shuttle_slot_in_half: int
    free_s: float = 0.0
    shuttle_busy_s: float = 0.0
    reader_busy_s: float = 0.0
    service_count: int = 0
    logical_request_count: int = 0
    bytes_read: int = 0
    active_cycle_s: float = 0.0


@dataclass(frozen=True)
class PanelRequestDetail:
    request_index: int
    arrival_s: float
    size_bytes: int
    merged_request_count: int
    platter_id: int
    zone_id: int
    row_id: int
    side: str
    level: int
    slot_in_half: int
    reader_level: int
    reader_slot_in_half: int
    shuttle_start_level: int
    shuttle_start_slot_in_half: int
    fetch_start_s: float
    move_to_glass_s: float
    move_to_glass_horizontal_m: float
    move_to_glass_horizontal_s: float
    move_to_glass_vertical_levels: int
    move_to_glass_vertical_s: float
    storage_pick_s: float
    move_to_reader_s: float
    move_to_reader_horizontal_m: float
    move_to_reader_horizontal_s: float
    move_to_reader_vertical_levels: int
    move_to_reader_vertical_s: float
    reader_load_s: float
    read_s: float
    drive_done_s: float
    reader_unload_s: float
    move_return_s: float
    move_return_horizontal_m: float
    move_return_horizontal_s: float
    move_return_vertical_levels: int
    move_return_vertical_s: float
    storage_place_s: float
    return_done_s: float
    latency_s: float
    cycle_s: float
    queue_wait_s: float


@dataclass(frozen=True)
class PanelStaticZoneResult:
    summary: dict[str, Any]
    details: list[PanelRequestDetail]
    zone_rows: list[dict[str, Any]]


@dataclass(frozen=True)
class MoveBreakdown:
    total_s: float
    horizontal_m: float
    horizontal_s: float
    vertical_levels: int
    vertical_s: float


def load_panel_static_zone_config(path: str | Path) -> PanelStaticZoneConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    base_dir = repository_root_for_config(config_path)
    config = PanelStaticZoneConfig(
        output_dir=_resolve_path(raw["output_dir"], base_dir),
        seed=int(raw.get("seed", 0)),
        geometry=PanelGeometryConfig(**raw["geometry"]),
        movement=PanelMovementConfig(**raw["movement"]),
        timing=PanelTimingConfig(**raw["timing"]),
        workload=PanelWorkloadConfig(**raw["workload"]),
    )
    config.validate()
    return config


def run_panel_static_zone(config: PanelStaticZoneConfig) -> PanelStaticZoneResult:
    simulator = PanelStaticZoneSimulator(config)
    requests = simulator.generate_requests()
    if config.workload.request_merge:
        requests = merge_panel_requests(requests)
    return simulator.run(requests)


def merge_panel_requests(requests: list[PanelRequest]) -> list[PanelRequest]:
    merged: dict[int, PanelRequest] = {}
    for request in requests:
        existing = merged.get(request.platter_id)
        if existing is None:
            merged[request.platter_id] = request
            continue
        merged[request.platter_id] = PanelRequest(
            request_index=existing.request_index,
            arrival_s=min(existing.arrival_s, request.arrival_s),
            size_bytes=existing.size_bytes + request.size_bytes,
            platter_id=existing.platter_id,
            zone_id=existing.zone_id,
            row_id=existing.row_id,
            side=existing.side,
            level=existing.level,
            slot_in_half=existing.slot_in_half,
            reader_level=existing.reader_level,
            reader_slot_in_half=existing.reader_slot_in_half,
            merged_request_count=existing.merged_request_count + request.merged_request_count,
        )
    return sorted(merged.values(), key=lambda request: (request.arrival_s, request.request_index))


def write_panel_static_zone_outputs(config: PanelStaticZoneConfig, result: PanelStaticZoneResult) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    _write_detail_csv(config.output_dir / "request_detail.csv", result.details)
    _write_zone_csv(config.output_dir / "zone_summary.csv", result.zone_rows)
    with (config.output_dir / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(result.summary, handle, indent=2)
        handle.write("\n")
    with (config.output_dir / "config.json").open("w", encoding="utf-8") as handle:
        json.dump(config.to_json_dict(), handle, indent=2)
        handle.write("\n")
    _write_analysis(config.output_dir / "PANEL_STATIC_ZONE_ANALYSIS.md", result)
    figures_dir = config.output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    try:
        write_panel_static_zone_figures(result, figures_dir)
    except ModuleNotFoundError as error:
        if error.name != "matplotlib":
            raise
        (figures_dir / "FIGURES_SKIPPED.txt").write_text(
            "matplotlib is not installed in this Python environment; CSV/JSON outputs were still written.\n",
            encoding="utf-8",
        )


class PanelStaticZoneSimulator:
    def __init__(self, config: PanelStaticZoneConfig) -> None:
        self.config = config
        self.geometry = config.geometry
        self.movement = config.movement
        self.timing = config.timing
        self.row_count = self.geometry.levels // self.geometry.zone_height_racks
        self.zone_count = self.row_count * 2
        self.zones = self._build_zones()

    def generate_requests(self) -> list[PanelRequest]:
        zone_rng = random.Random(self.config.seed + 17)
        location_rng = random.Random(self.config.seed + 29)
        requests = []
        for index in range(self.config.workload.batch_size):
            zone_id = self._choose_request_zone(index, zone_rng)
            local_level = location_rng.randrange(self.geometry.zone_height_racks)
            slot_in_half = location_rng.randrange(self.geometry.slots_per_half)
            requests.append(
                self.make_request(
                    request_index=index,
                    zone_id=zone_id,
                    local_level=local_level,
                    slot_in_half=slot_in_half,
                    size_bytes=self.config.workload.request_size_bytes,
                )
            )
        return requests

    def make_request(
        self,
        request_index: int,
        zone_id: int,
        local_level: int,
        slot_in_half: int,
        size_bytes: int,
        arrival_s: float = 0.0,
    ) -> PanelRequest:
        if not 0 <= zone_id < self.zone_count:
            raise ValueError("zone_id must be within the panel zone count")
        if not 0 <= local_level < self.geometry.zone_height_racks:
            raise ValueError("local_level must be within the zone height")
        if not 0 <= slot_in_half < self.geometry.slots_per_half:
            raise ValueError("slot_in_half must be within the half-panel slot range")
        zone = self.zones[zone_id]
        level = zone.row_id * self.geometry.zone_height_racks + local_level
        return PanelRequest(
            request_index=request_index,
            arrival_s=arrival_s,
            size_bytes=size_bytes,
            platter_id=self._platter_id_for_location(zone.zone_id, level, slot_in_half),
            zone_id=zone.zone_id,
            row_id=zone.row_id,
            side=zone.side,
            level=level,
            slot_in_half=slot_in_half,
            reader_level=zone.reader_level,
            reader_slot_in_half=zone.reader_slot_in_half,
        )

    def _choose_request_zone(self, index: int, rng: random.Random) -> int:
        workload = self.config.workload
        if workload.placement == "uniform_round_robin":
            return index % self.zone_count
        if workload.placement == "spatial_skew":
            if rng.random() < workload.hot_zone_fraction:
                return (workload.hot_zone + rng.randrange(workload.hot_zone_width)) % self.zone_count
            hot_zones = {
                (workload.hot_zone + offset) % self.zone_count for offset in range(workload.hot_zone_width)
            }
            cold_zones = [zone_id for zone_id in range(self.zone_count) if zone_id not in hot_zones]
            if not cold_zones:
                return rng.randrange(self.zone_count)
            return cold_zones[rng.randrange(len(cold_zones))]
        raise ValueError(f"unsupported workload placement: {workload.placement}")

    def _platter_id_for_location(self, zone_id: int, level: int, slot_in_half: int) -> int:
        row_start = self.zones[zone_id].row_id * self.geometry.zone_height_racks
        local_level = level - row_start
        local_slot = local_level * self.geometry.slots_per_half + slot_in_half
        return zone_id * self.geometry.zone_height_racks * self.geometry.slots_per_half + local_slot

    def run(self, requests: list[PanelRequest]) -> PanelStaticZoneResult:
        details = [self._serve(request) for request in requests]
        return PanelStaticZoneResult(
            summary=self._build_summary(details),
            details=details,
            zone_rows=self._build_zone_rows(),
        )

    def run_barrier_epochs(
        self,
        request_epochs: list[list[PanelRequest]],
    ) -> tuple[PanelStaticZoneResult, list[list[PanelRequestDetail]]]:
        all_details: list[PanelRequestDetail] = []
        epoch_details: list[list[PanelRequestDetail]] = []
        for requests in request_epochs:
            epoch_start_s = max((zone.free_s for zone in self.zones), default=0.0)
            current = [
                self._serve(replace(request, arrival_s=epoch_start_s))
                for request in requests
            ]
            epoch_details.append(current)
            all_details.extend(current)
        return (
            PanelStaticZoneResult(
                summary=self._build_summary(all_details),
                details=all_details,
                zone_rows=self._build_zone_rows(),
            ),
            epoch_details,
        )

    def _build_zones(self) -> list[ZoneState]:
        zones = []
        for row_id in range(self.row_count):
            row_start = row_id * self.geometry.zone_height_racks
            reader_level = min(row_start + self.geometry.zone_height_racks // 2, self.geometry.levels - 1)
            zones.append(
                ZoneState(
                    zone_id=row_id * 2,
                    row_id=row_id,
                    side="left",
                    reader_level=reader_level,
                    reader_slot_in_half=0,
                    shuttle_level=reader_level,
                    shuttle_slot_in_half=0,
                )
            )
            zones.append(
                ZoneState(
                    zone_id=row_id * 2 + 1,
                    row_id=row_id,
                    side="right",
                    reader_level=reader_level,
                    reader_slot_in_half=self.geometry.slots_per_half - 1,
                    shuttle_level=reader_level,
                    shuttle_slot_in_half=self.geometry.slots_per_half - 1,
                )
            )
        return zones

    def _serve(self, request: PanelRequest) -> PanelRequestDetail:
        zone = self.zones[request.zone_id]
        fetch_start_s = max(request.arrival_s, zone.free_s)
        shuttle_start_level = zone.shuttle_level
        shuttle_start_slot = zone.shuttle_slot_in_half
        move_to_glass = self._move_breakdown(
            shuttle_start_level,
            shuttle_start_slot,
            request.level,
            request.slot_in_half,
        )
        move_to_reader = self._move_breakdown(
            request.level,
            request.slot_in_half,
            request.reader_level,
            request.reader_slot_in_half,
        )
        read_s = self._read_time_s(request.size_bytes)
        move_return = self._move_breakdown(
            request.reader_level,
            request.reader_slot_in_half,
            request.level,
            request.slot_in_half,
        )

        drive_done_s = (
            fetch_start_s
            + move_to_glass.total_s
            + self.timing.storage_pick_s
            + move_to_reader.total_s
            + self.timing.reader_load_s
            + read_s
        )
        return_done_s = (
            drive_done_s
            + self.timing.reader_unload_s
            + move_return.total_s
            + self.timing.storage_place_s
        )
        cycle_s = return_done_s - fetch_start_s
        queue_wait_s = fetch_start_s - request.arrival_s

        zone.free_s = return_done_s
        zone.shuttle_level = request.level
        zone.shuttle_slot_in_half = request.slot_in_half
        zone.service_count += 1
        zone.logical_request_count += request.merged_request_count
        zone.bytes_read += request.size_bytes
        zone.active_cycle_s += cycle_s
        zone.reader_busy_s += self.timing.reader_load_s + read_s + self.timing.reader_unload_s
        zone.shuttle_busy_s += (
            move_to_glass.total_s
            + self.timing.storage_pick_s
            + move_to_reader.total_s
            + self.timing.reader_load_s
            + self.timing.reader_unload_s
            + move_return.total_s
            + self.timing.storage_place_s
        )

        return PanelRequestDetail(
            request_index=request.request_index,
            arrival_s=request.arrival_s,
            size_bytes=request.size_bytes,
            merged_request_count=request.merged_request_count,
            platter_id=request.platter_id,
            zone_id=request.zone_id,
            row_id=request.row_id,
            side=request.side,
            level=request.level,
            slot_in_half=request.slot_in_half,
            reader_level=request.reader_level,
            reader_slot_in_half=request.reader_slot_in_half,
            shuttle_start_level=shuttle_start_level,
            shuttle_start_slot_in_half=shuttle_start_slot,
            fetch_start_s=fetch_start_s,
            move_to_glass_s=move_to_glass.total_s,
            move_to_glass_horizontal_m=move_to_glass.horizontal_m,
            move_to_glass_horizontal_s=move_to_glass.horizontal_s,
            move_to_glass_vertical_levels=move_to_glass.vertical_levels,
            move_to_glass_vertical_s=move_to_glass.vertical_s,
            storage_pick_s=self.timing.storage_pick_s,
            move_to_reader_s=move_to_reader.total_s,
            move_to_reader_horizontal_m=move_to_reader.horizontal_m,
            move_to_reader_horizontal_s=move_to_reader.horizontal_s,
            move_to_reader_vertical_levels=move_to_reader.vertical_levels,
            move_to_reader_vertical_s=move_to_reader.vertical_s,
            reader_load_s=self.timing.reader_load_s,
            read_s=read_s,
            drive_done_s=drive_done_s,
            reader_unload_s=self.timing.reader_unload_s,
            move_return_s=move_return.total_s,
            move_return_horizontal_m=move_return.horizontal_m,
            move_return_horizontal_s=move_return.horizontal_s,
            move_return_vertical_levels=move_return.vertical_levels,
            move_return_vertical_s=move_return.vertical_s,
            storage_place_s=self.timing.storage_place_s,
            return_done_s=return_done_s,
            latency_s=drive_done_s - request.arrival_s,
            cycle_s=cycle_s,
            queue_wait_s=queue_wait_s,
        )

    def _move_time_s(self, src_level: int, src_slot: int, dst_level: int, dst_slot: int) -> float:
        return self._move_breakdown(src_level, src_slot, dst_level, dst_slot).total_s

    def _move_breakdown(self, src_level: int, src_slot: int, dst_level: int, dst_slot: int) -> MoveBreakdown:
        vertical_levels = abs(dst_level - src_level)
        vertical_s = vertical_levels * self.movement.vertical_s_per_level
        horizontal_m = abs(dst_slot - src_slot) * self._slot_width_m()
        horizontal_s = self._horizontal_time_s(horizontal_m)
        return MoveBreakdown(
            total_s=vertical_s + horizontal_s,
            horizontal_m=horizontal_m,
            horizontal_s=horizontal_s,
            vertical_levels=vertical_levels,
            vertical_s=vertical_s,
        )

    def _horizontal_time_s(self, distance_m: float) -> float:
        if distance_m <= 0:
            return 0.0
        vmax = self.movement.horizontal_max_m_s
        accel = self.movement.horizontal_accel_m_s2
        accel_distance = vmax * vmax / accel
        if distance_m <= accel_distance:
            travel_s = 2.0 * math.sqrt(distance_m / accel)
        else:
            travel_s = 2.0 * (vmax / accel) + (distance_m - accel_distance) / vmax
        return max(self.movement.horizontal_min_s, travel_s)

    def _read_time_s(self, size_bytes: int) -> float:
        return self.timing.reader_mount_s + self.timing.reader_base_s + (size_bytes / MIB) / self.timing.reader_mib_per_s

    def _slot_width_m(self) -> float:
        return self.geometry.half_panel_length_m / (self.geometry.slots_per_half - 1)

    def _build_summary(self, details: list[PanelRequestDetail]) -> dict[str, Any]:
        makespan_s = max((row.drive_done_s for row in details), default=0.0)
        system_drain_s = max((row.return_done_s for row in details), default=0.0)
        latencies = [row.latency_s for row in details]
        active_total = sum(row.cycle_s for row in details)
        request_count = sum(row.merged_request_count for row in details)
        service_operation_count = len(details)
        total_bytes = sum(row.size_bytes for row in details)
        drive_total = sum(
            row.move_to_glass_s
            + row.storage_pick_s
            + row.move_to_reader_s
            + row.reader_load_s
            + row.read_s
            for row in details
        )
        components = {
            "move_to_glass_s": sum(row.move_to_glass_s for row in details),
            "move_to_glass_horizontal_s": sum(row.move_to_glass_horizontal_s for row in details),
            "move_to_glass_vertical_s": sum(row.move_to_glass_vertical_s for row in details),
            "storage_pick_s": sum(row.storage_pick_s for row in details),
            "move_to_reader_s": sum(row.move_to_reader_s for row in details),
            "move_to_reader_horizontal_s": sum(row.move_to_reader_horizontal_s for row in details),
            "move_to_reader_vertical_s": sum(row.move_to_reader_vertical_s for row in details),
            "reader_load_s": sum(row.reader_load_s for row in details),
            "read_s": sum(row.read_s for row in details),
            "reader_unload_s": sum(row.reader_unload_s for row in details),
            "move_return_s": sum(row.move_return_s for row in details),
            "move_return_horizontal_s": sum(row.move_return_horizontal_s for row in details),
            "move_return_vertical_s": sum(row.move_return_vertical_s for row in details),
            "storage_place_s": sum(row.storage_place_s for row in details),
        }
        horizontal_distance_m = sum(
            row.move_to_glass_horizontal_m
            + row.move_to_reader_horizontal_m
            + row.move_return_horizontal_m
            for row in details
        )
        vertical_levels = sum(
            row.move_to_glass_vertical_levels
            + row.move_to_reader_vertical_levels
            + row.move_return_vertical_levels
            for row in details
        )
        aggregate_components = {
            "shuttle_movement_s": components["move_to_glass_s"]
            + components["move_to_reader_s"]
            + components["move_return_s"],
            "fixed_mechanical_s": components["storage_pick_s"]
            + components["reader_load_s"]
            + components["reader_unload_s"]
            + components["storage_place_s"],
            "reader_data_transfer_s": components["read_s"],
        }
        movement_components = {
            "horizontal_movement_s": components["move_to_glass_horizontal_s"]
            + components["move_to_reader_horizontal_s"]
            + components["move_return_horizontal_s"],
            "vertical_movement_s": components["move_to_glass_vertical_s"]
            + components["move_to_reader_vertical_s"]
            + components["move_return_vertical_s"],
        }
        zone_utils = [zone.shuttle_busy_s / system_drain_s if system_drain_s > 0 else 0.0 for zone in self.zones]
        reader_utils = [zone.reader_busy_s / system_drain_s if system_drain_s > 0 else 0.0 for zone in self.zones]
        ideal_balanced_cycle_lower_bound_s = active_total / self.zone_count if self.zone_count > 0 else 0.0
        static_capacity_s = self.zone_count * system_drain_s
        stranded_capacity_s = max(0.0, static_capacity_s - active_total)
        static_capacity_efficiency = active_total / static_capacity_s if static_capacity_s > 0 else 0.0
        ownership_slowdown_vs_ideal = (
            system_drain_s / ideal_balanced_cycle_lower_bound_s
            if ideal_balanced_cycle_lower_bound_s > 0
            else 0.0
        )
        return {
            "config": self.config.to_json_dict(),
            "layout": "n_rows_x_2_sides",
            "row_count": self.row_count,
            "zone_count": self.zone_count,
            "reader_count": self.zone_count,
            "shuttle_count": self.zone_count,
            "request_count": request_count,
            "service_operation_count": service_operation_count,
            "merged_request_count": request_count - service_operation_count,
            "requests_per_service": request_count / service_operation_count if service_operation_count > 0 else 0.0,
            "request_merge": self.config.workload.request_merge,
            "batch_size": self.config.workload.batch_size,
            "request_size_bytes": self.config.workload.request_size_bytes,
            "drive_makespan_s": makespan_s,
            "system_drain_s": system_drain_s,
            "throughput_req_per_s": request_count / makespan_s if makespan_s > 0 else 0.0,
            "throughput_req_per_s_drained": request_count / system_drain_s if system_drain_s > 0 else 0.0,
            "throughput_service_ops_per_s": service_operation_count / makespan_s if makespan_s > 0 else 0.0,
            "throughput_mib_per_s": (total_bytes / MIB) / makespan_s if makespan_s > 0 else 0.0,
            "latency_p50_s": _percentile(sorted(latencies), 0.50) if latencies else 0.0,
            "latency_p95_s": _percentile(sorted(latencies), 0.95) if latencies else 0.0,
            "latency_p99_s": _percentile(sorted(latencies), 0.99) if latencies else 0.0,
            "avg_cycle_s_per_service": active_total / service_operation_count if service_operation_count else 0.0,
            "avg_drive_service_s_per_service": drive_total / service_operation_count if service_operation_count else 0.0,
            "avg_cycle_s_per_request": active_total / request_count if request_count else 0.0,
            "avg_drive_service_s_per_request": drive_total / request_count if request_count else 0.0,
            "avg_queue_wait_s": mean([row.queue_wait_s for row in details]) if details else 0.0,
            "shuttle_utilization_avg": mean(zone_utils) if zone_utils else 0.0,
            "shuttle_utilization_max": max(zone_utils, default=0.0),
            "shuttle_utilization_min": min(zone_utils, default=0.0),
            "shuttle_utilization_std": pstdev(zone_utils) if zone_utils else 0.0,
            "reader_utilization_avg": mean(reader_utils) if reader_utils else 0.0,
            "reader_utilization_max": max(reader_utils, default=0.0),
            "reader_utilization_min": min(reader_utils, default=0.0),
            "reader_utilization_std": pstdev(reader_utils) if reader_utils else 0.0,
            "ideal_balanced_cycle_lower_bound_s": ideal_balanced_cycle_lower_bound_s,
            "static_capacity_s": static_capacity_s,
            "productive_cycle_s": active_total,
            "stranded_capacity_s": stranded_capacity_s,
            "stranded_capacity_share": stranded_capacity_s / static_capacity_s if static_capacity_s > 0 else 0.0,
            "static_capacity_efficiency": static_capacity_efficiency,
            "ownership_slowdown_vs_ideal": ownership_slowdown_vs_ideal,
            "horizontal_distance_m": horizontal_distance_m,
            "vertical_levels_traversed": vertical_levels,
            "component_totals_s": components,
            "aggregate_component_totals_s": aggregate_components,
            "movement_component_totals_s": movement_components,
            "movement_component_avg_s": {
                key: value / service_operation_count if service_operation_count else 0.0
                for key, value in movement_components.items()
            },
            "movement_component_shares": {
                key: value / aggregate_components["shuttle_movement_s"]
                if aggregate_components["shuttle_movement_s"] > 0
                else 0.0
                for key, value in movement_components.items()
            },
            "aggregate_component_avg_s": {
                key: value / service_operation_count if service_operation_count else 0.0
                for key, value in aggregate_components.items()
            },
            "aggregate_component_avg_s_per_request": {
                key: value / request_count if request_count else 0.0 for key, value in aggregate_components.items()
            },
            "aggregate_component_active_shares": {
                key: value / active_total if active_total > 0 else 0.0 for key, value in aggregate_components.items()
            },
            "component_active_shares": {
                key: value / active_total if active_total > 0 else 0.0 for key, value in components.items()
            },
            "component_drive_shares": {
                key: value / drive_total if drive_total > 0 and key
                in {"move_to_glass_s", "storage_pick_s", "move_to_reader_s", "reader_load_s", "read_s"}
                else 0.0
                for key, value in components.items()
            },
            "assumptions": [
                "The panel is split into vertical rows and two horizontal sides.",
                "Each zone spans half the panel length and zone_height_racks rack levels.",
                "Each zone owns exactly one shuttle and one local reader at the outer edge.",
                "The baseline uses direct fetch, reader service, and return-to-origin with no feeder buffer.",
                f"Workload placement is {self.config.workload.placement} and requests arrive as one batch at t=0.",
                "A zone shuttle remains reserved for a direct fetch-read-return cycle and finishes at the returned glass slot.",
                "When request_merge is enabled, requests to the same physical glass are served by one movement and summed reader bytes.",
            ],
        }

    def _build_zone_rows(self) -> list[dict[str, Any]]:
        system_drain_s = max((zone.free_s for zone in self.zones), default=0.0)
        rows = []
        for zone in self.zones:
            rows.append(
                {
                    "zone_id": zone.zone_id,
                    "row_id": zone.row_id,
                    "side": zone.side,
                    "reader_level": zone.reader_level,
                    "reader_slot_in_half": zone.reader_slot_in_half,
                    "logical_request_count": zone.logical_request_count,
                    "glass_service_count": zone.service_count,
                    "requests_per_service": zone.logical_request_count / zone.service_count if zone.service_count > 0 else 0.0,
                    "data_mib": zone.bytes_read / MIB,
                    "completion_s": zone.free_s,
                    "completion_h": zone.free_s / 3600.0,
                    "active_cycle_s": zone.active_cycle_s,
                    "active_cycle_h": zone.active_cycle_s / 3600.0,
                    "avg_cycle_s_per_service": zone.active_cycle_s / zone.service_count if zone.service_count > 0 else 0.0,
                    "avg_cycle_s_per_logical_request": zone.active_cycle_s / zone.logical_request_count
                    if zone.logical_request_count > 0
                    else 0.0,
                    "shuttle_busy_s": zone.shuttle_busy_s,
                    "reader_busy_s": zone.reader_busy_s,
                    "shuttle_utilization": zone.shuttle_busy_s / system_drain_s if system_drain_s > 0 else 0.0,
                    "reader_utilization": zone.reader_busy_s / system_drain_s if system_drain_s > 0 else 0.0,
                }
            )
        return rows


def write_panel_static_zone_figures(result: PanelStaticZoneResult, figures_dir: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(Path("results/.mplconfig").resolve()))
    os.environ.setdefault("XDG_CACHE_HOME", str(Path("results/.cache").resolve()))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    shares = result.summary["component_active_shares"]
    aggregate_shares = result.summary["aggregate_component_active_shares"]
    aggregate_avg = result.summary["aggregate_component_avg_s"]
    aggregate_labels = ["Shuttle movement", "Fixed hardware ops", "Reader transfer"]
    aggregate_keys = ["shuttle_movement_s", "fixed_mechanical_s", "reader_data_transfer_s"]
    aggregate_colors = ["#2F6B9A", "#4C9F70", "#6B5B95"]

    fig, ax = plt.subplots(figsize=(7.0, 3.8))
    bars = ax.bar(
        aggregate_labels,
        [aggregate_shares[key] * 100 for key in aggregate_keys],
        color=aggregate_colors,
    )
    for bar, key in zip(bars, aggregate_keys):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1.0,
            f"{aggregate_avg[key]:.1f}s\n{aggregate_shares[key] * 100:.1f}%",
            ha="center",
            va="bottom",
            fontsize=9,
            color="#1F2933",
        )
    ax.set_ylim(0, max(100.0, max(aggregate_shares[key] * 100 for key in aggregate_keys) + 12.0))
    ax.set_ylabel("Share of active cycle time (%)")
    ax.set_title("Static zone cycle cost by major behavior")
    _apply_style(ax)
    _save(fig, figures_dir, "fig1_aggregate_time_breakdown")

    labels = [
        "to glass",
        "pick",
        "to reader",
        "load",
        "read",
        "unload",
        "return move",
        "place back",
    ]
    keys = [
        "move_to_glass_s",
        "storage_pick_s",
        "move_to_reader_s",
        "reader_load_s",
        "read_s",
        "reader_unload_s",
        "move_return_s",
        "storage_place_s",
    ]
    fig, ax = plt.subplots(figsize=(7.6, 4.0))
    ax.bar(labels, [shares[key] * 100 for key in keys], color=["#2F6B9A", "#4C9F70", "#2F6B9A", "#D9822B", "#6B5B95", "#D9822B", "#2F6B9A", "#4C9F70"])
    ax.set_ylabel("Share of active cycle time (%)")
    ax.set_title("Static zone direct-service time breakdown")
    ax.tick_params(axis="x", rotation=25)
    _apply_style(ax)
    _save(fig, figures_dir, "fig2_detailed_time_breakdown")

    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    zone_ids = [row["zone_id"] for row in result.zone_rows]
    ax.bar(zone_ids, [row["shuttle_utilization"] * 100 for row in result.zone_rows], color="#2F6B9A", label="Shuttle")
    ax.bar(zone_ids, [row["reader_utilization"] * 100 for row in result.zone_rows], color="#D9822B", alpha=0.8, label="Reader")
    ax.set_xlabel("Zone")
    ax.set_ylabel("Utilization over system drain (%)")
    placement_label = str(result.summary["config"]["workload"]["placement"]).replace("_", " ")
    ax.set_title(f"Per-zone utilization under {placement_label}")
    ax.legend(frameon=False)
    _apply_style(ax)
    _save(fig, figures_dir, "fig3_zone_utilization")

    fig, ax1 = plt.subplots(figsize=(7.4, 4.0))
    data_gib = [row["data_mib"] / 1024 for row in result.zone_rows]
    completion_h = [row["completion_h"] for row in result.zone_rows]
    glass_services = [row["glass_service_count"] for row in result.zone_rows]
    bars = ax1.bar(zone_ids, data_gib, color="#4C9F70", label="Data read")
    ax1.set_xlabel("Zone")
    ax1.set_ylabel("Data read (GiB)", color="#4C9F70")
    ax1.tick_params(axis="y", colors="#4C9F70")
    for bar, services in zip(bars, glass_services):
        ax1.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.8,
            f"{services}",
            ha="center",
            va="bottom",
            fontsize=8,
            color="#1F2933",
        )

    ax2 = ax1.twinx()
    ax2.plot(zone_ids, completion_h, color="#2F6B9A", marker="o", linewidth=1.8, label="Completion time")
    ax2.set_ylabel("Completion time (h)", color="#2F6B9A")
    ax2.tick_params(axis="y", colors="#2F6B9A")
    ax1.set_title("Per-zone data volume and completion time")
    _apply_style(ax1)
    ax2.spines["top"].set_visible(False)
    ax2.spines["left"].set_visible(False)
    ax2.spines["right"].set_color("#9AA5B1")
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2, frameon=False, loc="upper right")
    _save(fig, figures_dir, "fig4_zone_data_and_completion")


def _write_detail_csv(path: Path, details: list[PanelRequestDetail]) -> None:
    fieldnames = list(PanelRequestDetail.__dataclass_fields__.keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for detail in details:
            writer.writerow(asdict(detail))


def _write_zone_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_analysis(path: Path, result: PanelStaticZoneResult) -> None:
    summary = result.summary
    shares = summary["component_active_shares"]
    aggregate_shares = summary["aggregate_component_active_shares"]
    aggregate_avg = summary["aggregate_component_avg_s"]
    aggregate_avg_per_request = summary["aggregate_component_avg_s_per_request"]
    aggregate_totals = summary["aggregate_component_totals_s"]
    movement_avg = summary["movement_component_avg_s"]
    movement_shares = summary["movement_component_shares"]
    lines = [
        "# Panel Static-Zone Baseline Analysis",
        "",
        "## Baseline setup",
        f"- Layout: {summary['row_count']} rows x 2 sides = {summary['zone_count']} zones.",
        f"- Each zone owns one shuttle and one local reader.",
        f"- Workload placement: {summary['config']['workload']['placement']}.",
        f"- Batch: {summary['request_count']} logical requests, {summary['request_size_bytes'] / MIB:.0f} MiB/request.",
        f"- Request merge: {summary['request_merge']} "
        f"({summary['service_operation_count']} glass services, {summary['requests_per_service']:.2f} requests/service).",
        f"- Drive makespan: {summary['drive_makespan_s'] / 3600:.2f} h.",
        f"- System drain including return: {summary['system_drain_s'] / 3600:.2f} h.",
        f"- Throughput: {summary['throughput_req_per_s']:.4f} req/s ({summary['throughput_mib_per_s']:.2f} MiB/s).",
        "",
        "## Major behavior breakdown",
        f"- Shuttle movement distance cost: {aggregate_avg['shuttle_movement_s']:.2f}s/glass service "
        f"({aggregate_avg_per_request['shuttle_movement_s']:.2f}s/logical request), "
        f"{aggregate_totals['shuttle_movement_s'] / 3600:.2f} total hours, "
        f"{aggregate_shares['shuttle_movement_s'] * 100:.1f}% of active cycle time.",
        f"- Fixed hardware operations: {aggregate_avg['fixed_mechanical_s']:.2f}s/glass service "
        f"({aggregate_avg_per_request['fixed_mechanical_s']:.2f}s/logical request), "
        f"{aggregate_totals['fixed_mechanical_s'] / 3600:.2f} total hours, "
        f"{aggregate_shares['fixed_mechanical_s'] * 100:.1f}% of active cycle time.",
        f"- Reader data transfer: {aggregate_avg['reader_data_transfer_s']:.2f}s/glass service "
        f"({aggregate_avg_per_request['reader_data_transfer_s']:.2f}s/logical request), "
        f"{aggregate_totals['reader_data_transfer_s'] / 3600:.2f} total hours, "
        f"{aggregate_shares['reader_data_transfer_s'] * 100:.1f}% of active cycle time.",
        "",
        "## Movement decomposition",
        f"- Horizontal movement: {movement_avg['horizontal_movement_s']:.2f}s/glass service, "
        f"{movement_shares['horizontal_movement_s'] * 100:.1f}% of movement time.",
        f"- Vertical movement: {movement_avg['vertical_movement_s']:.2f}s/glass service, "
        f"{movement_shares['vertical_movement_s'] * 100:.1f}% of movement time.",
        f"- Total horizontal distance: {summary['horizontal_distance_m'] / 1000:.2f} km.",
        f"- Total vertical levels traversed: {summary['vertical_levels_traversed']}.",
        "",
        "## Detailed active cycle time breakdown",
    ]
    for key, label in [
        ("move_to_glass_s", "move from current shuttle position to next glass"),
        ("storage_pick_s", "pick glass from rack"),
        ("move_to_reader_s", "move glass to reader"),
        ("reader_load_s", "load into reader"),
        ("read_s", "reader data transfer"),
        ("reader_unload_s", "unload from reader"),
        ("move_return_s", "move glass back to rack"),
        ("storage_place_s", "place glass back"),
    ]:
        lines.append(f"- {label}: {shares[key] * 100:.1f}%")
    lines.extend(
        [
            "",
            "## Static ownership efficiency",
            f"- Productive zone-time capacity: {summary['static_capacity_efficiency'] * 100:.1f}%.",
            f"- Stranded zone-time capacity: {summary['stranded_capacity_share'] * 100:.1f}%.",
            f"- Work-conserving cycle lower bound: {summary['ideal_balanced_cycle_lower_bound_s'] / 3600:.2f} h.",
            f"- Observed drain / balanced-work lower bound: {summary['ownership_slowdown_vs_ideal']:.2f}x.",
            "",
            "## Zone comparison",
            "| Zone | Side | Logical requests | Glass services | Data (GiB) | Completion (h) | Active processing (h) | Shuttle util | Reader util |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in result.zone_rows:
        lines.append(
            f"| {row['zone_id']} | {row['side']} | {row['logical_request_count']} | "
            f"{row['glass_service_count']} | {row['data_mib'] / 1024:.2f} | "
            f"{row['completion_h']:.2f} | {row['active_cycle_h']:.2f} | "
            f"{row['shuttle_utilization'] * 100:.1f}% | {row['reader_utilization'] * 100:.1f}% |"
        )
    lines.extend(
        [
            "",
            "## Bottleneck interpretation",
            f"- Average active cycle per glass service: {summary['avg_cycle_s_per_service']:.2f}s.",
            f"- Average active cycle per logical request: {summary['avg_cycle_s_per_request']:.2f}s.",
            f"- Average drive-visible service per glass service before drive_done: {summary['avg_drive_service_s_per_service']:.2f}s.",
            f"- Average drive-visible service per logical request before drive_done: {summary['avg_drive_service_s_per_request']:.2f}s.",
            f"- Average queue wait from batching: {summary['avg_queue_wait_s'] / 3600:.2f} h.",
            f"- Average shuttle utilization: {summary['shuttle_utilization_avg'] * 100:.1f}%.",
            f"- Average reader utilization: {summary['reader_utilization_avg'] * 100:.1f}%.",
            "- At the per-glass level, movement and mechanical handling dominate reader transfer.",
            (
                "- At the system level, fixed ownership and stranded cold-zone capacity dominate this skewed run."
                if summary["stranded_capacity_share"] >= 0.20
                else "- At the system level, static ownership uses the available zone capacity efficiently in this balanced run."
            ),
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _apply_style(ax) -> None:
    ax.set_facecolor("white")
    ax.set_axisbelow(True)
    ax.grid(True, axis="y", color="#D7DEE8", linewidth=0.8, zorder=0)
    ax.grid(False, axis="x")
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color("#9AA5B1")
    ax.spines["bottom"].set_color("#9AA5B1")
    ax.tick_params(colors="#1F2933", labelsize=9)
    ax.xaxis.label.set_color("#1F2933")
    ax.yaxis.label.set_color("#1F2933")
    ax.title.set_color("#1F2933")


def _save(fig, output_dir: Path, name: str) -> None:
    fig.tight_layout()
    fig.savefig(output_dir / f"{name}.pdf")
    fig.savefig(output_dir / f"{name}.png", dpi=300)
    import matplotlib.pyplot as plt

    plt.close(fig)


def _percentile(ordered: list[float], quantile: float) -> float:
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * quantile
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return ordered[int(pos)]
    weight = pos - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _resolve_path(value: str, base_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()
