from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import json
import math
import os
from pathlib import Path
import random
from statistics import mean
from typing import Any


MIB = 1024 * 1024


@dataclass(frozen=True)
class StaticGeometryConfig:
    levels: int
    slots_per_rack: int
    rack_length_m: float
    reader_level: int
    glass_capacity_bytes: int

    def validate(self) -> None:
        if self.levels <= 0:
            raise ValueError("geometry.levels must be positive")
        if self.slots_per_rack <= 1:
            raise ValueError("geometry.slots_per_rack must be greater than 1")
        if self.rack_length_m <= 0:
            raise ValueError("geometry.rack_length_m must be positive")
        if not 0 <= self.reader_level < self.levels:
            raise ValueError("geometry.reader_level must be within panel levels")
        if self.glass_capacity_bytes <= 0:
            raise ValueError("geometry.glass_capacity_bytes must be positive")


@dataclass(frozen=True)
class StaticMovementConfig:
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
class StaticTimingConfig:
    storage_pick_s: float
    storage_place_s: float
    reader_load_s: float
    reader_unload_s: float
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
class StaticFeederBufferConfig:
    enabled: bool
    slots: int
    allow_shuttle_holding: bool = False

    def validate(self) -> None:
        if self.slots < 0:
            raise ValueError("feeder_buffer.slots cannot be negative")
        if self.enabled and self.slots <= 0:
            raise ValueError("feeder_buffer.slots must be positive when enabled")


@dataclass(frozen=True)
class StaticWorkloadConfig:
    batch_size: int
    request_size_bytes: int
    skew_cases: list[str]
    moderate_hot_fraction: float
    heavy_hot_fraction: float
    shifting_hot_fraction: float
    shifting_phase_count: int
    shifting_phase_gap_s: float
    hot_zone: int = 0

    def validate(self) -> None:
        if self.batch_size <= 0:
            raise ValueError("workload.batch_size must be positive")
        if self.request_size_bytes <= 0:
            raise ValueError("workload.request_size_bytes must be positive")
        if not self.skew_cases:
            raise ValueError("workload.skew_cases cannot be empty")
        valid = {"uniform", "moderate_skew", "heavy_skew", "shifting_hotspot"}
        unknown = set(self.skew_cases) - valid
        if unknown:
            raise ValueError(f"unknown workload.skew_cases: {sorted(unknown)}")
        for name in ["moderate_hot_fraction", "heavy_hot_fraction", "shifting_hot_fraction"]:
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"workload.{name} must be between 0 and 1")
        if self.shifting_phase_count <= 0:
            raise ValueError("workload.shifting_phase_count must be positive")
        if self.shifting_phase_gap_s < 0:
            raise ValueError("workload.shifting_phase_gap_s cannot be negative")
        if self.hot_zone < 0:
            raise ValueError("workload.hot_zone cannot be negative")


@dataclass(frozen=True)
class StaticZoneConfig:
    output_dir: Path
    seed: int
    zone_counts: list[int]
    policies: list[str]
    write_detail: bool
    geometry: StaticGeometryConfig
    movement: StaticMovementConfig
    timing: StaticTimingConfig
    feeder_buffer: StaticFeederBufferConfig
    workload: StaticWorkloadConfig

    def validate(self) -> None:
        if not self.zone_counts:
            raise ValueError("zone_counts cannot be empty")
        if any(count <= 0 for count in self.zone_counts):
            raise ValueError("zone_counts must contain only positive values")
        if len(set(self.zone_counts)) != len(self.zone_counts):
            raise ValueError("zone_counts cannot contain duplicates")
        if any(self.geometry.slots_per_rack % count != 0 for count in self.zone_counts):
            raise ValueError("geometry.slots_per_rack must be divisible by every zone_count")
        valid_policies = {"static_zone", "shared_pool"}
        unknown_policies = set(self.policies) - valid_policies
        if unknown_policies:
            raise ValueError(f"unknown policies: {sorted(unknown_policies)}")
        if not self.policies:
            raise ValueError("policies cannot be empty")
        self.geometry.validate()
        self.movement.validate()
        self.timing.validate()
        self.feeder_buffer.validate()
        self.workload.validate()
        if self.workload.hot_zone >= min(self.zone_counts):
            raise ValueError("workload.hot_zone must be valid for the smallest zone_count")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "output_dir": str(self.output_dir),
            "seed": self.seed,
            "zone_counts": self.zone_counts,
            "policies": self.policies,
            "write_detail": self.write_detail,
            "geometry": asdict(self.geometry),
            "movement": asdict(self.movement),
            "timing": asdict(self.timing),
            "feeder_buffer": asdict(self.feeder_buffer),
            "workload": asdict(self.workload),
        }


@dataclass
class ShuttleState:
    shuttle_id: int
    free_s: float
    level: int
    slot: int
    busy_s: float = 0.0
    task_count: int = 0


@dataclass
class ReaderState:
    reader_id: int
    level: int
    slot: int
    available_s: float = 0.0
    busy_s: float = 0.0
    waiting_for_glass_s: float = 0.0
    service_count: int = 0
    buffer_leave_times: list[float] | None = None


@dataclass(frozen=True)
class StaticRequest:
    request_index: int
    arrival_s: float
    size_bytes: int
    platter_id: int
    zone: int
    level: int
    slot: int


@dataclass(frozen=True)
class StaticRequestDetail:
    policy: str
    skew_case: str
    zone_count: int
    request_index: int
    arrival_s: float
    size_bytes: int
    platter_id: int
    request_zone: int
    level: int
    slot: int
    fetch_shuttle_id: int
    reader_id: int
    reader_home_zone: int
    fetch_start_s: float
    feeder_ready_s: float
    reader_load_start_s: float
    read_start_s: float
    drive_done_s: float
    reader_unload_done_s: float
    latency_s: float
    fetch_s: float
    read_s: float
    reader_waiting_for_glass_s: float
    feeder_buffer_wait_for_slot_s: float


@dataclass(frozen=True)
class StaticZoneRunResult:
    policy: str
    skew_case: str
    zone_count: int
    summary: dict[str, Any]
    details: list[StaticRequestDetail]
    resource_rows: list[dict[str, Any]]


def load_static_zone_config(path: str | Path) -> StaticZoneConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    base_dir = config_path.parent.parent if config_path.parent.name == "configs" else Path.cwd()
    config = StaticZoneConfig(
        output_dir=_resolve_path(raw["output_dir"], base_dir),
        seed=int(raw.get("seed", 0)),
        zone_counts=list(raw["zone_counts"]),
        policies=list(raw["policies"]),
        write_detail=bool(raw.get("write_detail", True)),
        geometry=StaticGeometryConfig(**raw["geometry"]),
        movement=StaticMovementConfig(**raw["movement"]),
        timing=StaticTimingConfig(**raw["timing"]),
        feeder_buffer=StaticFeederBufferConfig(**raw["feeder_buffer"]),
        workload=StaticWorkloadConfig(**raw["workload"]),
    )
    config.validate()
    return config


def run_static_zone_experiment(config: StaticZoneConfig) -> list[StaticZoneRunResult]:
    results: list[StaticZoneRunResult] = []
    for zone_count in config.zone_counts:
        for skew_case in config.workload.skew_cases:
            requests = _generate_requests(config, zone_count, skew_case)
            for policy in config.policies:
                simulator = StaticZoneSimulator(config, zone_count, policy, skew_case)
                results.append(simulator.run(requests))
    return results


def write_static_zone_outputs(config: StaticZoneConfig, results: list[StaticZoneRunResult]) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    _write_summary_csv(config.output_dir / "summary.csv", results)
    _write_run_detail_csv(config.output_dir / "run_detail.csv", results)
    for result in results:
        run_dir = config.output_dir / result.skew_case / result.policy / f"zones_{result.zone_count:02d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        with (run_dir / "summary.json").open("w", encoding="utf-8") as handle:
            json.dump(result.summary, handle, indent=2)
            handle.write("\n")
        if config.write_detail:
            _write_request_detail_csv(run_dir / "request_detail.csv", result.details)

    with (config.output_dir / "config.json").open("w", encoding="utf-8") as handle:
        json.dump(config.to_json_dict(), handle, indent=2)
        handle.write("\n")

    figures_dir = config.output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    try:
        write_static_zone_figures(results, figures_dir)
        skipped_path = figures_dir / "FIGURES_SKIPPED.txt"
        if skipped_path.exists():
            skipped_path.unlink()
    except ModuleNotFoundError as error:
        if error.name != "matplotlib":
            raise
        (figures_dir / "FIGURES_SKIPPED.txt").write_text(
            "matplotlib is not installed in this Python environment; CSV/JSON outputs were still written.\n",
            encoding="utf-8",
        )
    _write_analysis(config.output_dir / "STATIC_ZONE_ANALYSIS.md", results)


class StaticZoneSimulator:
    def __init__(self, config: StaticZoneConfig, zone_count: int, policy: str, skew_case: str) -> None:
        self.config = config
        self.geometry = config.geometry
        self.movement = config.movement
        self.timing = config.timing
        self.zone_count = zone_count
        self.policy = policy
        self.skew_case = skew_case
        self.zone_bounds = _zone_bounds(self.geometry.slots_per_rack, zone_count)
        self.readers = [
            ReaderState(
                reader_id=zone,
                level=self.geometry.reader_level,
                slot=self.zone_bounds[zone][1],
                buffer_leave_times=[],
            )
            for zone in range(zone_count)
        ]
        self.shuttles = [
            ShuttleState(
                shuttle_id=zone,
                free_s=0.0,
                level=self.geometry.reader_level,
                slot=self.zone_bounds[zone][1],
            )
            for zone in range(zone_count)
        ]
        self.zone_reader_wait_s = [0.0 for _ in range(zone_count)]
        self.zone_completion_s = [0.0 for _ in range(zone_count)]
        self.zone_service_count = [0 for _ in range(zone_count)]
        self.feeder_buffer_wait_for_slot_s = 0.0

    def run(self, requests: list[StaticRequest]) -> StaticZoneRunResult:
        details = [self._serve(request) for request in requests]
        summary = self._build_summary(details)
        resources = self._build_resource_rows(details)
        return StaticZoneRunResult(
            policy=self.policy,
            skew_case=self.skew_case,
            zone_count=self.zone_count,
            summary=summary,
            details=details,
            resource_rows=resources,
        )

    def _serve(self, request: StaticRequest) -> StaticRequestDetail:
        choice = self._choose_assignment(request)
        shuttle = self.shuttles[choice["shuttle_id"]]
        reader = self.readers[choice["reader_id"]]
        prior_reader_available_s = reader.available_s

        fetch_start_s = choice["fetch_start_s"]
        feeder_ready_s = choice["feeder_ready_s"]
        reader_load_start_s = choice["reader_load_start_s"]
        read_start_s = choice["read_start_s"]
        drive_done_s = choice["drive_done_s"]
        reader_unload_done_s = choice["reader_unload_done_s"]
        reader_wait_s = max(0.0, feeder_ready_s - prior_reader_available_s)

        shuttle.free_s = feeder_ready_s
        shuttle.level = reader.level
        shuttle.slot = reader.slot
        shuttle.busy_s += feeder_ready_s - fetch_start_s
        shuttle.task_count += 1

        reader.available_s = reader_unload_done_s
        reader.busy_s += self.timing.reader_load_s + choice["read_s"] + self.timing.reader_unload_s
        reader.waiting_for_glass_s += reader_wait_s
        reader.service_count += 1
        if reader.buffer_leave_times is None:
            reader.buffer_leave_times = []
        reader.buffer_leave_times.append(reader_load_start_s)

        self.zone_service_count[request.zone] += 1
        self.zone_completion_s[request.zone] = max(self.zone_completion_s[request.zone], drive_done_s)
        self.zone_reader_wait_s[request.zone] += reader_wait_s
        self.feeder_buffer_wait_for_slot_s += choice["feeder_buffer_wait_for_slot_s"]

        return StaticRequestDetail(
            policy=self.policy,
            skew_case=self.skew_case,
            zone_count=self.zone_count,
            request_index=request.request_index,
            arrival_s=request.arrival_s,
            size_bytes=request.size_bytes,
            platter_id=request.platter_id,
            request_zone=request.zone,
            level=request.level,
            slot=request.slot,
            fetch_shuttle_id=shuttle.shuttle_id,
            reader_id=reader.reader_id,
            reader_home_zone=reader.reader_id,
            fetch_start_s=fetch_start_s,
            feeder_ready_s=feeder_ready_s,
            reader_load_start_s=reader_load_start_s,
            read_start_s=read_start_s,
            drive_done_s=drive_done_s,
            reader_unload_done_s=reader_unload_done_s,
            latency_s=drive_done_s - request.arrival_s,
            fetch_s=feeder_ready_s - fetch_start_s,
            read_s=choice["read_s"],
            reader_waiting_for_glass_s=reader_wait_s,
            feeder_buffer_wait_for_slot_s=choice["feeder_buffer_wait_for_slot_s"],
        )

    def _choose_assignment(self, request: StaticRequest) -> dict[str, Any]:
        if self.policy == "static_zone":
            shuttle_ids = [request.zone]
            reader_ids = [request.zone]
        elif self.policy == "shared_pool":
            shuttle_ids = list(range(self.zone_count))
            reader_ids = list(range(self.zone_count))
        else:
            raise ValueError(f"unsupported policy: {self.policy}")

        choices = []
        for shuttle_id in shuttle_ids:
            shuttle = self.shuttles[shuttle_id]
            for reader_id in reader_ids:
                reader = self.readers[reader_id]
                choices.append(self._candidate(request, shuttle, reader))
        return min(
            choices,
            key=lambda choice: (
                choice["drive_done_s"],
                choice["feeder_ready_s"],
                choice["shuttle_id"],
                choice["reader_id"],
            ),
        )

    def _candidate(self, request: StaticRequest, shuttle: ShuttleState, reader: ReaderState) -> dict[str, Any]:
        slot_free_s = self._reader_slot_free_s(reader)
        earliest_start_s = max(request.arrival_s, shuttle.free_s)
        move_to_glass_s = self._move_time_s(shuttle.level, shuttle.slot, request.level, request.slot)
        move_to_reader_s = self._move_time_s(request.level, request.slot, reader.level, reader.slot)
        pre_buffer_s = move_to_glass_s + self.timing.storage_pick_s + move_to_reader_s
        fetch_start_s = earliest_start_s
        if self.config.feeder_buffer.enabled and not self.config.feeder_buffer.allow_shuttle_holding:
            fetch_start_s = max(fetch_start_s, slot_free_s - pre_buffer_s)
        buffer_arrival_s = fetch_start_s + pre_buffer_s
        place_start_s = max(buffer_arrival_s, slot_free_s)
        feeder_ready_s = place_start_s + self.timing.storage_place_s
        feeder_wait_s = (
            max(0.0, place_start_s - buffer_arrival_s)
            if self.config.feeder_buffer.allow_shuttle_holding
            else max(0.0, fetch_start_s - earliest_start_s)
        )

        reader_load_start_s = max(reader.available_s, feeder_ready_s)
        read_start_s = reader_load_start_s + self.timing.reader_load_s
        read_s = self._read_time_s(request.size_bytes)
        drive_done_s = read_start_s + read_s
        reader_unload_done_s = drive_done_s + self.timing.reader_unload_s
        return {
            "shuttle_id": shuttle.shuttle_id,
            "reader_id": reader.reader_id,
            "fetch_start_s": fetch_start_s,
            "feeder_ready_s": feeder_ready_s,
            "reader_load_start_s": reader_load_start_s,
            "read_start_s": read_start_s,
            "drive_done_s": drive_done_s,
            "reader_unload_done_s": reader_unload_done_s,
            "read_s": read_s,
            "feeder_buffer_wait_for_slot_s": feeder_wait_s,
        }

    def _reader_slot_free_s(self, reader: ReaderState) -> float:
        if not self.config.feeder_buffer.enabled:
            return reader.available_s
        if reader.buffer_leave_times is None:
            return 0.0
        if reader.service_count < self.config.feeder_buffer.slots:
            return 0.0
        return reader.buffer_leave_times[reader.service_count - self.config.feeder_buffer.slots]

    def _move_time_s(self, src_level: int, src_slot: int, dst_level: int, dst_slot: int) -> float:
        vertical_s = abs(dst_level - src_level) * self.movement.vertical_s_per_level
        horizontal_m = abs(dst_slot - src_slot) * self._slot_width_m()
        return vertical_s + self._horizontal_time_s(horizontal_m)

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
        return self.geometry.rack_length_m / (self.geometry.slots_per_rack - 1)

    def _build_summary(self, details: list[StaticRequestDetail]) -> dict[str, Any]:
        first_arrival_s = min((row.arrival_s for row in details), default=0.0)
        last_arrival_s = max((row.arrival_s for row in details), default=0.0)
        last_drive_done_s = max((row.drive_done_s for row in details), default=0.0)
        last_reader_available_s = max((reader.available_s for reader in self.readers), default=0.0)
        drive_makespan_s = max(last_drive_done_s - first_arrival_s, 0.0)
        system_drain_s = max(last_reader_available_s - first_arrival_s, 0.0)
        latencies = [row.latency_s for row in details]
        shuttle_utils = [shuttle.busy_s / system_drain_s if system_drain_s > 0 else 0.0 for shuttle in self.shuttles]
        reader_utils = [reader.busy_s / system_drain_s if system_drain_s > 0 else 0.0 for reader in self.readers]
        total_bytes = sum(row.size_bytes for row in details)
        hot_zone = max(range(self.zone_count), key=lambda zone: self.zone_service_count[zone])
        return {
            "policy": self.policy,
            "skew_case": self.skew_case,
            "zone_count": self.zone_count,
            "shuttle_count": self.zone_count,
            "reader_count": self.zone_count,
            "request_count": len(details),
            "arrival_span_s": max(last_arrival_s - first_arrival_s, 0.0),
            "drive_makespan_s": drive_makespan_s,
            "system_drain_s": system_drain_s,
            "throughput_req_per_s": len(details) / drive_makespan_s if drive_makespan_s > 0 else 0.0,
            "throughput_mib_per_s": (total_bytes / MIB) / drive_makespan_s if drive_makespan_s > 0 else 0.0,
            "latency_p50_s": _percentile(sorted(latencies), 0.50) if latencies else 0.0,
            "latency_p95_s": _percentile(sorted(latencies), 0.95) if latencies else 0.0,
            "latency_p99_s": _percentile(sorted(latencies), 0.99) if latencies else 0.0,
            "reader_utilization_avg": mean(reader_utils) if reader_utils else 0.0,
            "reader_utilization_max": max(reader_utils, default=0.0),
            "reader_utilization_min": min(reader_utils, default=0.0),
            "reader_utilization_std": _stddev(reader_utils),
            "shuttle_utilization_avg": mean(shuttle_utils) if shuttle_utils else 0.0,
            "shuttle_utilization_max": max(shuttle_utils, default=0.0),
            "shuttle_utilization_min": min(shuttle_utils, default=0.0),
            "shuttle_utilization_std": _stddev(shuttle_utils),
            "reader_waiting_for_glass_s": sum(reader.waiting_for_glass_s for reader in self.readers),
            "feeder_buffer_wait_for_slot_s": self.feeder_buffer_wait_for_slot_s,
            "zone_service_count": _join_numbers(self.zone_service_count),
            "zone_completion_time_s": _join_numbers(self.zone_completion_s),
            "zone_reader_wait_s": _join_numbers(self.zone_reader_wait_s),
            "zone_shuttle_busy_s": _join_numbers([shuttle.busy_s for shuttle in self.shuttles]),
            "hot_zone": hot_zone,
            "hot_zone_request_count": self.zone_service_count[hot_zone],
            "hot_zone_completion_time_s": self.zone_completion_s[hot_zone],
            "assumptions": [
                "Static-zone runs use one shuttle and one local reader per zone.",
                "Static-zone shuttles and readers only serve requests whose glass home slot is in the same zone.",
                "Shared-pool runs use the same number of shuttles/readers but allow any shuttle and any reader to serve a request.",
                "This v1 model treats one request as one physical glass service and does not merge repeated glass requests.",
                "Fetch service includes move-to-glass, storage pick, move-to-reader, and reader-side placement; glass return is not modeled in v1.",
            ],
        }

    def _build_resource_rows(self, details: list[StaticRequestDetail]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        system_drain_s = max((reader.available_s for reader in self.readers), default=0.0)
        for zone in range(self.zone_count):
            rows.append(
                {
                    "policy": self.policy,
                    "skew_case": self.skew_case,
                    "zone_count": self.zone_count,
                    "resource_type": "zone",
                    "resource_id": zone,
                    "request_count": self.zone_service_count[zone],
                    "completion_time_s": self.zone_completion_s[zone],
                    "reader_waiting_for_glass_s": self.zone_reader_wait_s[zone],
                    "busy_s": "",
                    "utilization": "",
                }
            )
        for shuttle in self.shuttles:
            rows.append(
                {
                    "policy": self.policy,
                    "skew_case": self.skew_case,
                    "zone_count": self.zone_count,
                    "resource_type": "shuttle",
                    "resource_id": shuttle.shuttle_id,
                    "request_count": shuttle.task_count,
                    "completion_time_s": shuttle.free_s,
                    "reader_waiting_for_glass_s": "",
                    "busy_s": shuttle.busy_s,
                    "utilization": shuttle.busy_s / system_drain_s if system_drain_s > 0 else 0.0,
                }
            )
        for reader in self.readers:
            rows.append(
                {
                    "policy": self.policy,
                    "skew_case": self.skew_case,
                    "zone_count": self.zone_count,
                    "resource_type": "reader",
                    "resource_id": reader.reader_id,
                    "request_count": reader.service_count,
                    "completion_time_s": reader.available_s,
                    "reader_waiting_for_glass_s": reader.waiting_for_glass_s,
                    "busy_s": reader.busy_s,
                    "utilization": reader.busy_s / system_drain_s if system_drain_s > 0 else 0.0,
                }
            )
        return rows


def write_static_zone_figures(results: list[StaticZoneRunResult], figures_dir: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(Path("outputs/.mplconfig").resolve()))
    os.environ.setdefault("XDG_CACHE_HOME", str(Path("outputs/.cache").resolve()))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = [result.summary for result in results]
    _plot_throughput(rows, figures_dir, plt)
    _plot_speedup(rows, figures_dir, plt)
    _plot_utilization_std(rows, figures_dir, plt, "shuttle")
    _plot_utilization_std(rows, figures_dir, plt, "reader")
    _plot_tail_latency(rows, figures_dir, plt)
    _plot_zone_completion(results, figures_dir, plt)


def _generate_requests(config: StaticZoneConfig, zone_count: int, skew_case: str) -> list[StaticRequest]:
    seed = config.seed + zone_count * 1009 + sum(ord(ch) for ch in skew_case)
    rng = random.Random(seed)
    bounds = _zone_bounds(config.geometry.slots_per_rack, zone_count)
    requests: list[StaticRequest] = []
    batch_size = config.workload.batch_size
    phase_size = max(1, math.ceil(batch_size / config.workload.shifting_phase_count))
    for index in range(batch_size):
        phase = index // phase_size
        zone = _choose_zone(config, zone_count, skew_case, phase, rng)
        left, right = bounds[zone]
        level = rng.randrange(config.geometry.levels)
        slot = rng.randrange(left, right + 1)
        arrival_s = 0.0
        if skew_case == "shifting_hotspot":
            arrival_s = phase * config.workload.shifting_phase_gap_s
        requests.append(
            StaticRequest(
                request_index=index,
                arrival_s=arrival_s,
                size_bytes=config.workload.request_size_bytes,
                platter_id=index,
                zone=zone,
                level=level,
                slot=slot,
            )
        )
    return requests


def _choose_zone(
    config: StaticZoneConfig,
    zone_count: int,
    skew_case: str,
    phase: int,
    rng: random.Random,
) -> int:
    if skew_case == "uniform":
        return rng.randrange(zone_count)
    if skew_case == "moderate_skew":
        return _weighted_hot_zone(zone_count, config.workload.hot_zone, config.workload.moderate_hot_fraction, rng)
    if skew_case == "heavy_skew":
        return _weighted_hot_zone(zone_count, config.workload.hot_zone, config.workload.heavy_hot_fraction, rng)
    if skew_case == "shifting_hotspot":
        hot_zone = phase % zone_count
        return _weighted_hot_zone(zone_count, hot_zone, config.workload.shifting_hot_fraction, rng)
    raise ValueError(f"unsupported skew_case: {skew_case}")


def _weighted_hot_zone(zone_count: int, hot_zone: int, hot_fraction: float, rng: random.Random) -> int:
    if zone_count == 1:
        return 0
    sample = rng.random()
    if sample < hot_fraction:
        return hot_zone
    cold_zone = rng.randrange(zone_count - 1)
    if cold_zone >= hot_zone:
        cold_zone += 1
    return cold_zone


def _zone_bounds(slots_per_rack: int, zone_count: int) -> list[tuple[int, int]]:
    zone_width = slots_per_rack // zone_count
    return [(zone * zone_width, (zone + 1) * zone_width - 1) for zone in range(zone_count)]


def _write_summary_csv(path: Path, results: list[StaticZoneRunResult]) -> None:
    if not results:
        return
    fields = [
        "policy",
        "skew_case",
        "zone_count",
        "shuttle_count",
        "reader_count",
        "request_count",
        "arrival_span_s",
        "drive_makespan_s",
        "system_drain_s",
        "throughput_req_per_s",
        "throughput_mib_per_s",
        "latency_p50_s",
        "latency_p95_s",
        "latency_p99_s",
        "reader_utilization_avg",
        "reader_utilization_max",
        "reader_utilization_min",
        "reader_utilization_std",
        "shuttle_utilization_avg",
        "shuttle_utilization_max",
        "shuttle_utilization_min",
        "shuttle_utilization_std",
        "reader_waiting_for_glass_s",
        "feeder_buffer_wait_for_slot_s",
        "zone_service_count",
        "zone_completion_time_s",
        "zone_reader_wait_s",
        "zone_shuttle_busy_s",
        "hot_zone",
        "hot_zone_request_count",
        "hot_zone_completion_time_s",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for result in results:
            writer.writerow({field: result.summary.get(field) for field in fields})


def _write_run_detail_csv(path: Path, results: list[StaticZoneRunResult]) -> None:
    rows = [row for result in results for row in result.resource_rows]
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_request_detail_csv(path: Path, details: list[StaticRequestDetail]) -> None:
    if not details:
        return
    fields = list(StaticRequestDetail.__dataclass_fields__.keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for detail in details:
            writer.writerow(asdict(detail))


def _write_analysis(path: Path, results: list[StaticZoneRunResult]) -> None:
    rows = [result.summary for result in results]
    lines = [
        "# Static Zone V1 Analysis",
        "",
        "This experiment compares one-zone/one-shuttle/one-reader static partitioning against a shared-pool baseline with the same number of shuttles and readers.",
        "",
        "## Key observations",
    ]
    for skew_case in sorted({row["skew_case"] for row in rows}):
        lines.append(f"### {skew_case}")
        for zone_count in sorted({int(row["zone_count"]) for row in rows if row["skew_case"] == skew_case}):
            static = _find_summary(rows, "static_zone", skew_case, zone_count)
            shared = _find_summary(rows, "shared_pool", skew_case, zone_count)
            if static is None or shared is None:
                continue
            speedup = shared["throughput_req_per_s"] / static["throughput_req_per_s"] if static["throughput_req_per_s"] else 0.0
            lines.append(
                f"- {zone_count} zones: shared/static throughput = {speedup:.2f}x; "
                f"static shuttle util std = {static['shuttle_utilization_std']:.3f}, "
                f"shared shuttle util std = {shared['shuttle_utilization_std']:.3f}."
            )
    lines.extend(
        [
            "",
            "## Modeling assumptions",
            "- Static-zone runs use exactly one shuttle and one local reader per zone.",
            "- Shared-pool runs keep the same reader and shuttle count but remove the static ownership constraint.",
            "- One synthetic request is one physical glass service; request merge is disabled in this baseline.",
            "- Fetch service ends when the shuttle places the glass at the selected reader-side feeder buffer.",
            "- Glass return is not modeled in this v1 experiment; this keeps the first baseline focused on fetch-side load imbalance.",
            "- Shifting-hotspot requests are phased over time; the other skew cases arrive as a batch at t=0.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _find_summary(rows: list[dict[str, Any]], policy: str, skew_case: str, zone_count: int) -> dict[str, Any] | None:
    return next(
        (
            row
            for row in rows
            if row["policy"] == policy and row["skew_case"] == skew_case and int(row["zone_count"]) == zone_count
        ),
        None,
    )


def _plot_throughput(rows: list[dict[str, Any]], figures_dir: Path, plt) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(9.2, 6.4), sharex=True)
    skews = sorted({row["skew_case"] for row in rows})
    for ax, skew_case in zip(axes.flat, skews):
        for policy, color, marker in [("static_zone", "#2F6B9A", "o"), ("shared_pool", "#D9822B", "s")]:
            series = sorted(
                [row for row in rows if row["skew_case"] == skew_case and row["policy"] == policy],
                key=lambda row: int(row["zone_count"]),
            )
            ax.plot(
                [row["zone_count"] for row in series],
                [row["throughput_req_per_s"] for row in series],
                marker=marker,
                linewidth=1.8,
                color=color,
                label=policy,
            )
        ax.set_title(skew_case)
        ax.set_xlabel("Zones / shuttles / readers")
        ax.set_ylabel("Throughput (req/s)")
        ax.set_xticks(sorted({int(row["zone_count"]) for row in rows}))
        _apply_style(ax)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, loc="upper center", ncol=2)
    _save(fig, figures_dir, "fig1_throughput_vs_zone_count")


def _plot_speedup(rows: list[dict[str, Any]], figures_dir: Path, plt) -> None:
    zone_counts = sorted({int(row["zone_count"]) for row in rows})
    skews = sorted({row["skew_case"] for row in rows})
    fig, ax = plt.subplots(figsize=(7.4, 4.0))
    width = 0.8 / max(1, len(zone_counts))
    positions = list(range(len(skews)))
    for index, zone_count in enumerate(zone_counts):
        values = []
        for skew_case in skews:
            static = _find_summary(rows, "static_zone", skew_case, zone_count)
            shared = _find_summary(rows, "shared_pool", skew_case, zone_count)
            values.append(
                shared["throughput_req_per_s"] / static["throughput_req_per_s"]
                if static and shared and static["throughput_req_per_s"]
                else 0.0
            )
        offset = (index - (len(zone_counts) - 1) / 2) * width
        ax.bar([pos + offset for pos in positions], values, width=width, label=f"{zone_count} zones")
    ax.axhline(1.0, color="#7B8794", linewidth=1.0, linestyle="--")
    ax.set_xticks(positions, skews, rotation=15, ha="right")
    ax.set_ylabel("Shared-pool throughput / static-zone throughput")
    ax.set_title("Shared-pool speedup grows when requests are spatially skewed")
    ax.legend(frameon=False, fontsize=8, ncol=2)
    _apply_style(ax)
    _save(fig, figures_dir, "fig2_shared_speedup_under_skew")


def _plot_utilization_std(rows: list[dict[str, Any]], figures_dir: Path, plt, resource: str) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    skews = sorted({row["skew_case"] for row in rows})
    for policy, color, marker in [("static_zone", "#2F6B9A", "o"), ("shared_pool", "#D9822B", "s")]:
        series = []
        for skew_case in skews:
            subset = [row for row in rows if row["policy"] == policy and row["skew_case"] == skew_case]
            series.append(mean(float(row[f"{resource}_utilization_std"]) for row in subset))
        ax.plot(skews, series, marker=marker, linewidth=1.8, color=color, label=policy)
    ax.set_ylabel(f"{resource.title()} utilization stddev")
    ax.set_title(f"{resource.title()} imbalance across skew cases")
    ax.tick_params(axis="x", rotation=15)
    ax.legend(frameon=False)
    _apply_style(ax)
    _save(fig, figures_dir, f"fig3_{resource}_utilization_imbalance")


def _plot_tail_latency(rows: list[dict[str, Any]], figures_dir: Path, plt) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    heavy = [row for row in rows if row["skew_case"] == "heavy_skew"]
    if not heavy:
        heavy = rows
    for policy, color, marker in [("static_zone", "#2F6B9A", "o"), ("shared_pool", "#D9822B", "s")]:
        series = sorted([row for row in heavy if row["policy"] == policy], key=lambda row: int(row["zone_count"]))
        ax.plot(
            [row["zone_count"] for row in series],
            [row["latency_p95_s"] for row in series],
            marker=marker,
            linewidth=1.8,
            color=color,
            label=f"{policy} p95",
        )
        ax.plot(
            [row["zone_count"] for row in series],
            [row["latency_p99_s"] for row in series],
            marker=marker,
            linewidth=1.2,
            linestyle="--",
            color=color,
            label=f"{policy} p99",
        )
    ax.set_xlabel("Zones / shuttles / readers")
    ax.set_ylabel("Latency (s)")
    ax.set_title("Tail latency under heavy spatial skew")
    ax.legend(frameon=False, fontsize=8, ncol=2)
    _apply_style(ax)
    _save(fig, figures_dir, "fig4_tail_latency_heavy_skew")


def _plot_zone_completion(results: list[StaticZoneRunResult], figures_dir: Path, plt) -> None:
    candidates = [result for result in results if result.skew_case == "heavy_skew"]
    if not candidates:
        return
    zone_count = max(result.zone_count for result in candidates)
    selected = [result for result in candidates if result.zone_count == zone_count]
    fig, ax = plt.subplots(figsize=(7.4, 4.0))
    width = 0.36
    zones = list(range(zone_count))
    for index, policy in enumerate(["static_zone", "shared_pool"]):
        result = next((item for item in selected if item.policy == policy), None)
        if result is None:
            continue
        completion = _split_numbers(result.summary["zone_completion_time_s"])
        offset = -width / 2 if index == 0 else width / 2
        ax.bar([zone + offset for zone in zones], completion, width=width, label=policy)
    ax.set_xlabel("Home zone")
    ax.set_ylabel("Last request completion time (s)")
    ax.set_title(f"Zone completion imbalance under heavy skew ({zone_count} zones)")
    ax.legend(frameon=False)
    _apply_style(ax)
    _save(fig, figures_dir, "fig5_zone_completion_heavy_skew")


def _apply_style(ax) -> None:
    ax.set_facecolor("white")
    ax.grid(True, axis="y", color="#D7DEE8", linewidth=0.8)
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
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(output_dir / f"{name}.pdf")
    fig.savefig(output_dir / f"{name}.png", dpi=300)
    import matplotlib.pyplot as plt

    plt.close(fig)


def _join_numbers(values: list[float] | list[int]) -> str:
    return ";".join(f"{value:.6f}" if isinstance(value, float) else str(value) for value in values)


def _split_numbers(value: str) -> list[float]:
    return [float(part) for part in value.split(";") if part]


def _stddev(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    avg = mean(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / len(values))


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
