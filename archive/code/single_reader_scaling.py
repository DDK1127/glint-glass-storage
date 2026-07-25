from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any

from .trace import TraceRequest, iter_trace


MIB = 1024 * 1024


@dataclass(frozen=True)
class GeometryConfig:
    levels: int
    slots_per_rack: int
    rack_length_m: float
    reader_level: int
    reader_slot: int
    platter_capacity_bytes: int
    placement_mode: str = "offset"
    synthetic_stripe_bytes: int | None = None
    synthetic_platter_count: int | None = None
    synthetic_hash_seed: int = 0

    def validate(self) -> None:
        if self.levels <= 0:
            raise ValueError("geometry.levels must be positive")
        if self.slots_per_rack <= 1:
            raise ValueError("geometry.slots_per_rack must be greater than 1")
        if self.rack_length_m <= 0:
            raise ValueError("geometry.rack_length_m must be positive")
        if not 0 <= self.reader_level < self.levels:
            raise ValueError("geometry.reader_level must be within panel levels")
        if not 0 <= self.reader_slot < self.slots_per_rack:
            raise ValueError("geometry.reader_slot must be within rack slots")
        if self.platter_capacity_bytes <= 0:
            raise ValueError("geometry.platter_capacity_bytes must be positive")
        if self.placement_mode not in {"offset", "synthetic_hash"}:
            raise ValueError("geometry.placement_mode must be 'offset' or 'synthetic_hash'")
        if self.placement_mode == "synthetic_hash":
            if self.synthetic_stripe_bytes is None or self.synthetic_stripe_bytes <= 0:
                raise ValueError("geometry.synthetic_stripe_bytes must be positive for synthetic_hash placement")
            if self.synthetic_platter_count is None or self.synthetic_platter_count <= 0:
                raise ValueError("geometry.synthetic_platter_count must be positive for synthetic_hash placement")


@dataclass(frozen=True)
class MovementConfig:
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
class ReaderConfig:
    count: int

    def validate(self) -> None:
        if self.count != 1:
            raise ValueError("single-reader scaling requires reader.count = 1")


@dataclass(frozen=True)
class TimingConfig:
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
class ConflictConfig:
    enabled: bool
    penalty_s: float
    window_s: float

    def validate(self) -> None:
        if self.penalty_s < 0:
            raise ValueError("conflict_penalty.penalty_s cannot be negative")
        if self.window_s < 0:
            raise ValueError("conflict_penalty.window_s cannot be negative")


@dataclass(frozen=True)
class FeederBufferConfig:
    enabled: bool = False
    slots: int = 0
    shuttle_place_s: float = 0.0
    return_policy: str = "fetch_priority"
    allow_shuttle_holding: bool = True

    def validate(self) -> None:
        if self.slots < 0:
            raise ValueError("feeder_buffer.slots cannot be negative")
        if self.enabled and self.slots <= 0:
            raise ValueError("feeder_buffer.slots must be positive when feeder_buffer.enabled is true")
        if self.shuttle_place_s < 0:
            raise ValueError("feeder_buffer.shuttle_place_s cannot be negative")
        if self.return_policy != "fetch_priority":
            raise ValueError("feeder_buffer.return_policy currently only supports 'fetch_priority'")


@dataclass(frozen=True)
class ScalingConfig:
    trace_path: Path
    output_dir: Path
    max_requests: int | None
    shuttle_counts: list[int]
    batch_sizes: list[int] | None
    arrival_mode: str
    request_merge: bool
    geometry: GeometryConfig
    movement: MovementConfig
    reader: ReaderConfig
    timing: TimingConfig
    conflict_penalty: ConflictConfig
    feeder_buffer: FeederBufferConfig
    saturation_threshold: float

    def validate(self) -> None:
        if not self.trace_path.exists():
            raise FileNotFoundError(f"trace_path does not exist: {self.trace_path}")
        if self.max_requests is not None and self.max_requests <= 0:
            raise ValueError("max_requests must be positive when set")
        if not self.shuttle_counts:
            raise ValueError("shuttle_counts cannot be empty")
        if any(count <= 0 for count in self.shuttle_counts):
            raise ValueError("shuttle_counts must contain only positive integers")
        if len(set(self.shuttle_counts)) != len(self.shuttle_counts):
            raise ValueError("shuttle_counts cannot contain duplicates")
        if self.batch_sizes is not None:
            if not self.batch_sizes:
                raise ValueError("batch_sizes cannot be empty when set")
            if any(size <= 0 for size in self.batch_sizes):
                raise ValueError("batch_sizes must contain only positive integers")
            if len(set(self.batch_sizes)) != len(self.batch_sizes):
                raise ValueError("batch_sizes cannot contain duplicates")
            if self.max_requests is not None and max(self.batch_sizes) > self.max_requests:
                raise ValueError("max_requests must be at least the largest batch size")
        if self.arrival_mode not in {"trace", "batch_at_t0"}:
            raise ValueError("arrival_mode must be 'trace' or 'batch_at_t0'")
        if self.batch_sizes is not None and self.arrival_mode != "batch_at_t0":
            raise ValueError("batch_sizes requires arrival_mode = 'batch_at_t0'")
        if self.request_merge and self.arrival_mode != "batch_at_t0":
            raise ValueError("request_merge currently requires arrival_mode = 'batch_at_t0'")
        if self.saturation_threshold < 0:
            raise ValueError("saturation_threshold cannot be negative")
        self.geometry.validate()
        self.movement.validate()
        self.reader.validate()
        self.timing.validate()
        self.conflict_penalty.validate()
        self.feeder_buffer.validate()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "trace_path": str(self.trace_path),
            "output_dir": str(self.output_dir),
            "max_requests": self.max_requests,
            "shuttle_counts": self.shuttle_counts,
            "batch_sizes": self.batch_sizes,
            "arrival_mode": self.arrival_mode,
            "request_merge": self.request_merge,
            "geometry": asdict(self.geometry),
            "movement": asdict(self.movement),
            "reader": asdict(self.reader),
            "timing": asdict(self.timing),
            "conflict_penalty": asdict(self.conflict_penalty),
            "feeder_buffer": asdict(self.feeder_buffer),
            "saturation_threshold": self.saturation_threshold,
        }


@dataclass(frozen=True)
class PlatterPlacement:
    platter_id: int
    level: int
    slot: int


@dataclass
class ShuttleState:
    shuttle_id: int
    free_s: float
    level: int
    slot: int
    busy_s: float = 0.0
    task_count: int = 0


@dataclass(frozen=True)
class WorkRequest:
    index: int
    arrival_s: float
    io_type: str
    lun: int
    offset: int
    size_bytes: int
    observed_response_s: float | None
    merged_request_count: int = 1


@dataclass(frozen=True)
class ScalingRequestDetail:
    request_index: int
    arrival_s: float
    offset: int
    size_bytes: int
    merged_request_count: int
    platter_id: int
    level: int
    slot: int
    fetch_shuttle_id: int
    fetch_start_s: float
    fetch_done_s: float
    feeder_buffer_ready_s: float
    reader_load_start_s: float
    read_start_s: float
    drive_done_s: float
    return_shuttle_id: int
    return_start_s: float
    reader_unload_done_s: float
    return_done_s: float
    latency_s: float
    fetch_s: float
    read_s: float
    feeder_buffer_wait_for_slot_s: float
    reader_waiting_for_glass_s: float
    reader_blocked_by_return_s: float
    fetch_conflict_count: int
    return_conflict_count: int


@dataclass(frozen=True)
class ScalingRunResult:
    shuttle_count: int
    summary: dict[str, Any]
    details: list[ScalingRequestDetail]


def load_scaling_config(path: str | Path) -> ScalingConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    base_dir = config_path.parent.parent if config_path.parent.name == "configs" else Path.cwd()
    feeder_buffer_raw = raw.get("feeder_buffer", {})
    config = ScalingConfig(
        trace_path=_resolve_path(raw["trace_path"], base_dir),
        output_dir=_resolve_path(raw["output_dir"], base_dir),
        max_requests=raw.get("max_requests"),
        shuttle_counts=list(raw["shuttle_counts"]),
        batch_sizes=list(raw["batch_sizes"]) if raw.get("batch_sizes") is not None else None,
        arrival_mode=raw.get("arrival_mode", "trace"),
        request_merge=bool(raw.get("request_merge", False)),
        geometry=GeometryConfig(**raw["geometry"]),
        movement=MovementConfig(**raw["movement"]),
        reader=ReaderConfig(**raw["reader"]),
        timing=TimingConfig(**raw["timing"]),
        conflict_penalty=ConflictConfig(**raw["conflict_penalty"]),
        feeder_buffer=FeederBufferConfig(**feeder_buffer_raw),
        saturation_threshold=float(raw["saturation_threshold"]),
    )
    config.validate()
    return config


def run_scaling_experiment(config: ScalingConfig) -> list[ScalingRunResult]:
    load_limit = config.max_requests
    if config.batch_sizes is not None:
        load_limit = max(config.batch_sizes)
    requests, input_stats = _load_read_requests(config.trace_path, load_limit)
    if config.batch_sizes is not None:
        return _run_batch_scaling_experiment(config, requests, input_stats)

    results: list[ScalingRunResult] = []
    previous_throughput: float | None = None
    saturation_seen = False

    for shuttle_count in config.shuttle_counts:
        simulator = SingleReaderScalingSimulator(config, shuttle_count, input_stats)
        result = simulator.run(requests)
        throughput = float(result.summary["throughput_req_per_s"])
        marginal_gain = None
        saturation_flag = False
        if previous_throughput is not None and previous_throughput > 0:
            marginal_gain = (throughput - previous_throughput) / previous_throughput
            saturation_flag = marginal_gain < config.saturation_threshold
        if saturation_flag:
            saturation_seen = True
        result.summary["marginal_throughput_gain"] = marginal_gain
        result.summary["saturation_flag"] = saturation_flag
        result.summary["saturation_seen"] = saturation_seen
        results.append(result)
        previous_throughput = throughput

    return results


def _run_batch_scaling_experiment(
    config: ScalingConfig,
    requests: list[WorkRequest],
    input_stats: dict[str, int],
) -> list[ScalingRunResult]:
    results: list[ScalingRunResult] = []
    for batch_size in config.batch_sizes or []:
        if batch_size > len(requests):
            raise ValueError(f"batch_size {batch_size} exceeds loaded read request count {len(requests)}")
        batch_requests = _as_batch_at_t0(requests[:batch_size])
        if config.request_merge:
            batch_requests = _merge_requests_by_platter(batch_requests, config.geometry)
        previous_throughput: float | None = None
        saturation_seen = False
        for shuttle_count in config.shuttle_counts:
            simulator = SingleReaderScalingSimulator(config, shuttle_count, input_stats)
            result = simulator.run(batch_requests)
            throughput = float(result.summary["throughput_req_per_s"])
            marginal_gain = None
            saturation_flag = False
            if previous_throughput is not None and previous_throughput > 0:
                marginal_gain = (throughput - previous_throughput) / previous_throughput
                saturation_flag = marginal_gain < config.saturation_threshold
            if saturation_flag:
                saturation_seen = True
            result.summary["batch_size"] = batch_size
            result.summary["arrival_mode"] = config.arrival_mode
            result.summary["request_merge"] = config.request_merge
            result.summary["marginal_throughput_gain"] = marginal_gain
            result.summary["saturation_flag"] = saturation_flag
            result.summary["saturation_seen"] = saturation_seen
            results.append(result)
            previous_throughput = throughput
    return results


def write_scaling_outputs(config: ScalingConfig, results: list[ScalingRunResult]) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = config.output_dir / "summary.csv"
    has_batches = any("batch_size" in result.summary for result in results)
    summary_fields = [
        "batch_size",
        "arrival_mode",
        "request_merge",
        "shuttle_count",
        "request_count",
        "service_operation_count",
        "merged_request_count",
        "ignored_writes",
        "arrival_span_s",
        "drive_makespan_s",
        "system_drain_s",
        "throughput_req_per_s",
        "throughput_mib_per_s",
        "reader_utilization",
        "reader_load_time_s",
        "reader_unload_time_s",
        "reader_pipeline_utilization",
        "shuttle_utilization_avg",
        "shuttle_utilization_max",
        "latency_p50_s",
        "latency_p95_s",
        "latency_p99_s",
        "reader_waiting_for_glass_s",
        "reader_blocked_by_return_s",
        "feeder_buffer_enabled",
        "feeder_buffer_slots",
        "feeder_buffer_wait_for_slot_s",
        "feeder_buffer_max_occupancy",
        "conflict_count",
        "marginal_throughput_gain",
        "saturation_flag",
        "saturation_seen",
    ]
    if not has_batches:
        summary_fields = [
            field
            for field in summary_fields
            if field not in {"batch_size", "arrival_mode", "request_merge"}
        ]
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields)
        writer.writeheader()
        for result in results:
            writer.writerow({key: result.summary.get(key) for key in summary_fields})

    for result in results:
        if has_batches:
            run_dir = (
                config.output_dir
                / f"batch_{int(result.summary['batch_size']):05d}"
                / f"shuttles_{result.shuttle_count:02d}"
            )
        else:
            run_dir = config.output_dir / f"shuttles_{result.shuttle_count:02d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        _write_detail_csv(run_dir / "request_detail.csv", result.details)
        with (run_dir / "summary.json").open("w", encoding="utf-8") as handle:
            json.dump(result.summary, handle, indent=2)
            handle.write("\n")

    with (config.output_dir / "config.json").open("w", encoding="utf-8") as handle:
        json.dump(config.to_json_dict(), handle, indent=2)
        handle.write("\n")


class SingleReaderScalingSimulator:
    def __init__(
        self,
        config: ScalingConfig,
        shuttle_count: int,
        input_stats: dict[str, int],
    ) -> None:
        self.config = config
        self.geometry = config.geometry
        self.movement = config.movement
        self.timing = config.timing
        self.conflict = config.conflict_penalty
        self.shuttle_count = shuttle_count
        self.input_stats = input_stats
        self.shuttles = [
            ShuttleState(
                shuttle_id=index,
                free_s=0.0,
                level=self.geometry.reader_level,
                slot=self.geometry.reader_slot,
            )
            for index in range(shuttle_count)
        ]
        self.reader_available_s = 0.0
        self.reader_busy_s = 0.0
        self.reader_waiting_for_glass_s = 0.0
        self.reader_blocked_by_return_s = 0.0
        self.feeder_buffer_wait_for_slot_s = 0.0
        self.feeder_buffer_max_occupancy = 0
        self.conflict_count = 0
        self.lane_intervals: dict[int, list[tuple[float, float]]] = {
            level: [] for level in range(self.geometry.levels)
        }
        self.reader_ingress_intervals: list[tuple[float, float]] = []

    def run(self, requests: list[WorkRequest]) -> ScalingRunResult:
        if self.config.feeder_buffer.enabled:
            return self._run_feeder_buffer(requests)
        details = [self._serve(request) for request in requests]
        summary = self._build_summary(details)
        return ScalingRunResult(
            shuttle_count=self.shuttle_count,
            summary=summary,
            details=details,
        )

    def _run_feeder_buffer(self, requests: list[WorkRequest]) -> ScalingRunResult:
        fetch_rows: list[dict[str, Any]] = []
        buffer_leave_times: list[float] = []
        reader_available_s = 0.0
        buffer_wait_for_slot_s = 0.0
        max_occupancy = 0

        for request_index, request in enumerate(requests):
            placement = self._place(request.offset)
            slot_free_s = 0.0
            if request_index >= self.config.feeder_buffer.slots:
                slot_free_s = buffer_leave_times[request_index - self.config.feeder_buffer.slots]

            fetch_choice = self._choose_feeder_fetch_shuttle(placement, request.arrival_s, slot_free_s)
            fetch_shuttle = self.shuttles[fetch_choice["shuttle_id"]]
            fetch_start_s = fetch_choice["start_s"]
            fetch_penalty_s, fetch_conflicts = self._conflict_penalty(
                fetch_choice["lane_intervals"],
                fetch_choice["reader_interval"],
            )
            feeder_ready_s = fetch_choice["base_done_s"] + fetch_penalty_s
            fetch_busy_s = feeder_ready_s - fetch_start_s
            buffer_wait_for_slot_s += fetch_choice["buffer_wait_for_slot_s"]
            self._record_intervals(fetch_choice["lane_intervals"], fetch_choice["reader_interval"])

            fetch_shuttle.free_s = feeder_ready_s
            fetch_shuttle.level = self.geometry.reader_level
            fetch_shuttle.slot = self.geometry.reader_slot
            fetch_shuttle.busy_s += fetch_busy_s
            fetch_shuttle.task_count += 1

            prior_reader_available_s = reader_available_s
            reader_load_start_s = max(prior_reader_available_s, feeder_ready_s)
            read_start_s = reader_load_start_s + self.timing.reader_load_s
            read_s = self._read_time_s(request.size_bytes)
            drive_done_s = read_start_s + read_s
            reader_unload_done_s = drive_done_s + self.timing.reader_unload_s
            reader_available_s = reader_unload_done_s
            buffer_leave_times.append(reader_load_start_s)

            self.reader_busy_s += read_s
            reader_waiting_for_glass_s = max(0.0, feeder_ready_s - prior_reader_available_s)
            self.reader_waiting_for_glass_s += reader_waiting_for_glass_s
            self.reader_blocked_by_return_s += self.timing.reader_unload_s

            fetch_rows.append(
                {
                    "request": request,
                    "placement": placement,
                    "fetch_shuttle_id": fetch_shuttle.shuttle_id,
                    "fetch_start_s": fetch_start_s,
                    "fetch_done_s": feeder_ready_s,
                    "feeder_buffer_ready_s": feeder_ready_s,
                    "reader_load_start_s": reader_load_start_s,
                    "read_start_s": read_start_s,
                    "drive_done_s": drive_done_s,
                    "reader_unload_done_s": reader_unload_done_s,
                    "latency_s": drive_done_s - request.arrival_s,
                    "fetch_s": fetch_busy_s,
                    "read_s": read_s,
                    "feeder_buffer_wait_for_slot_s": fetch_choice["buffer_wait_for_slot_s"],
                    "reader_waiting_for_glass_s": reader_waiting_for_glass_s,
                    "reader_blocked_by_return_s": self.timing.reader_unload_s,
                    "fetch_conflict_count": fetch_conflicts,
                }
            )

        max_occupancy = _max_buffer_occupancy(
            [(row["feeder_buffer_ready_s"], row["reader_load_start_s"]) for row in fetch_rows]
        )
        details = self._schedule_feeder_returns(fetch_rows)
        self.feeder_buffer_wait_for_slot_s = buffer_wait_for_slot_s
        self.feeder_buffer_max_occupancy = min(max_occupancy, self.config.feeder_buffer.slots)
        summary = self._build_summary(details)
        return ScalingRunResult(
            shuttle_count=self.shuttle_count,
            summary=summary,
            details=details,
        )

    def _serve(self, request: TraceRequest) -> ScalingRequestDetail:
        placement = self._place(request.offset)
        reader_ready_s = max(self.reader_available_s, request.arrival_s)
        fetch_choice = self._choose_fetch_shuttle(placement, reader_ready_s)
        fetch_shuttle = self.shuttles[fetch_choice["shuttle_id"]]

        fetch_start_s = max(reader_ready_s, fetch_shuttle.free_s)
        fetch_penalty_s, fetch_conflicts = self._conflict_penalty(
            fetch_choice["lane_intervals"],
            fetch_choice["reader_interval"],
        )
        fetch_done_s = fetch_start_s + fetch_choice["base_duration_s"] + fetch_penalty_s
        fetch_busy_s = fetch_choice["base_duration_s"] + fetch_penalty_s
        self._record_intervals(fetch_choice["lane_intervals"], fetch_choice["reader_interval"])

        fetch_shuttle.free_s = fetch_done_s
        fetch_shuttle.level = self.geometry.reader_level
        fetch_shuttle.slot = self.geometry.reader_slot
        fetch_shuttle.busy_s += fetch_busy_s
        fetch_shuttle.task_count += 1

        read_start_s = fetch_done_s
        read_s = self._read_time_s(request.size_bytes)
        drive_done_s = read_start_s + read_s
        self.reader_busy_s += read_s
        self.reader_waiting_for_glass_s += max(0.0, fetch_done_s - reader_ready_s)

        return_choice = self._choose_return_shuttle(placement, drive_done_s)
        return_shuttle = self.shuttles[return_choice["shuttle_id"]]
        return_start_s = max(drive_done_s, return_shuttle.free_s)
        return_penalty_s, return_conflicts = self._conflict_penalty(
            return_choice["lane_intervals"],
            return_choice["reader_interval"],
        )
        reader_unload_done_s = (
            return_start_s
            + return_choice["move_to_reader_s"]
            + self.timing.reader_unload_s
            + return_penalty_s
        )
        return_done_s = reader_unload_done_s + return_choice["move_to_origin_s"] + self.timing.storage_place_s
        return_busy_s = return_done_s - return_start_s
        self._record_intervals(return_choice["lane_intervals"], return_choice["reader_interval"])

        return_shuttle.free_s = return_done_s
        return_shuttle.level = placement.level
        return_shuttle.slot = placement.slot
        return_shuttle.busy_s += return_busy_s
        return_shuttle.task_count += 1

        self.reader_blocked_by_return_s += max(0.0, reader_unload_done_s - drive_done_s)
        self.reader_available_s = reader_unload_done_s
        self.conflict_count += fetch_conflicts + return_conflicts

        return ScalingRequestDetail(
            request_index=request.index,
            arrival_s=request.arrival_s,
            offset=request.offset,
            size_bytes=request.size_bytes,
            merged_request_count=request.merged_request_count,
            platter_id=placement.platter_id,
            level=placement.level,
            slot=placement.slot,
            fetch_shuttle_id=fetch_shuttle.shuttle_id,
            fetch_start_s=fetch_start_s,
            fetch_done_s=fetch_done_s,
            feeder_buffer_ready_s=fetch_done_s,
            reader_load_start_s=fetch_done_s - self.timing.reader_load_s,
            read_start_s=read_start_s,
            drive_done_s=drive_done_s,
            return_shuttle_id=return_shuttle.shuttle_id,
            return_start_s=return_start_s,
            reader_unload_done_s=reader_unload_done_s,
            return_done_s=return_done_s,
            latency_s=drive_done_s - request.arrival_s,
            fetch_s=fetch_done_s - fetch_start_s,
            read_s=read_s,
            feeder_buffer_wait_for_slot_s=0.0,
            reader_waiting_for_glass_s=max(0.0, fetch_done_s - reader_ready_s),
            reader_blocked_by_return_s=max(0.0, reader_unload_done_s - drive_done_s),
            fetch_conflict_count=fetch_conflicts,
            return_conflict_count=return_conflicts,
        )

    def _choose_feeder_fetch_shuttle(
        self,
        placement: PlatterPlacement,
        arrival_s: float,
        buffer_slot_free_s: float,
    ) -> dict[str, Any]:
        choices = []
        for shuttle in self.shuttles:
            earliest_start_s = max(arrival_s, shuttle.free_s)
            start_s = earliest_start_s
            move_to_glass_s = self._move_time_s(shuttle.level, shuttle.slot, placement.level, placement.slot)
            move_to_buffer_s = self._move_time_s(
                placement.level,
                placement.slot,
                self.geometry.reader_level,
                self.geometry.reader_slot,
            )
            pre_buffer_s = move_to_glass_s + self.timing.storage_pick_s + move_to_buffer_s
            if not self.config.feeder_buffer.allow_shuttle_holding:
                start_s = max(start_s, buffer_slot_free_s - pre_buffer_s)
            buffer_arrival_s = start_s + move_to_glass_s + self.timing.storage_pick_s + move_to_buffer_s
            place_start_s = max(buffer_arrival_s, buffer_slot_free_s)
            buffer_wait_for_slot_s = (
                max(0.0, place_start_s - buffer_arrival_s)
                if self.config.feeder_buffer.allow_shuttle_holding
                else max(0.0, start_s - earliest_start_s)
            )
            place_s = self.config.feeder_buffer.shuttle_place_s
            lane_intervals = self._lane_intervals_for_move(
                start_s,
                shuttle.level,
                shuttle.slot,
                placement.level,
                placement.slot,
            )
            lane_intervals.extend(
                self._lane_intervals_for_move(
                    start_s + move_to_glass_s + self.timing.storage_pick_s,
                    placement.level,
                    placement.slot,
                    self.geometry.reader_level,
                    self.geometry.reader_slot,
                )
            )
            reader_interval = (place_start_s, place_start_s + place_s)
            penalty_s, conflict_count = self._conflict_penalty(lane_intervals, reader_interval)
            base_done_s = place_start_s + place_s
            choices.append(
                {
                    "shuttle_id": shuttle.shuttle_id,
                    "start_s": start_s,
                    "base_done_s": base_done_s,
                    "done_s": base_done_s + penalty_s,
                    "conflict_count": conflict_count,
                    "lane_intervals": lane_intervals,
                    "reader_interval": reader_interval,
                    "buffer_wait_for_slot_s": buffer_wait_for_slot_s,
                }
            )
        return min(choices, key=lambda choice: (choice["done_s"], choice["conflict_count"], choice["shuttle_id"]))

    def _schedule_feeder_returns(self, fetch_rows: list[dict[str, Any]]) -> list[ScalingRequestDetail]:
        details: list[ScalingRequestDetail] = []
        for row in sorted(fetch_rows, key=lambda item: (item["reader_unload_done_s"], item["request"].index)):
            request = row["request"]
            placement = row["placement"]
            return_choice = self._choose_feeder_return_shuttle(placement, row["reader_unload_done_s"])
            return_shuttle = self.shuttles[return_choice["shuttle_id"]]
            return_start_s = max(row["reader_unload_done_s"], return_shuttle.free_s)
            return_penalty_s, return_conflicts = self._conflict_penalty(
                return_choice["lane_intervals"],
                return_choice["reader_interval"],
            )
            return_done_s = return_choice["base_done_s"] + return_penalty_s
            return_busy_s = return_done_s - return_start_s
            self._record_intervals(return_choice["lane_intervals"], return_choice["reader_interval"])

            return_shuttle.free_s = return_done_s
            return_shuttle.level = placement.level
            return_shuttle.slot = placement.slot
            return_shuttle.busy_s += return_busy_s
            return_shuttle.task_count += 1
            self.conflict_count += row["fetch_conflict_count"] + return_conflicts

            details.append(
                ScalingRequestDetail(
                    request_index=request.index,
                    arrival_s=request.arrival_s,
                    offset=request.offset,
                    size_bytes=request.size_bytes,
                    merged_request_count=request.merged_request_count,
                    platter_id=placement.platter_id,
                    level=placement.level,
                    slot=placement.slot,
                    fetch_shuttle_id=row["fetch_shuttle_id"],
                    fetch_start_s=row["fetch_start_s"],
                    fetch_done_s=row["fetch_done_s"],
                    feeder_buffer_ready_s=row["feeder_buffer_ready_s"],
                    reader_load_start_s=row["reader_load_start_s"],
                    read_start_s=row["read_start_s"],
                    drive_done_s=row["drive_done_s"],
                    return_shuttle_id=return_shuttle.shuttle_id,
                    return_start_s=return_start_s,
                    reader_unload_done_s=row["reader_unload_done_s"],
                    return_done_s=return_done_s,
                    latency_s=row["latency_s"],
                    fetch_s=row["fetch_s"],
                    read_s=row["read_s"],
                    feeder_buffer_wait_for_slot_s=row["feeder_buffer_wait_for_slot_s"],
                    reader_waiting_for_glass_s=row["reader_waiting_for_glass_s"],
                    reader_blocked_by_return_s=row["reader_blocked_by_return_s"],
                    fetch_conflict_count=row["fetch_conflict_count"],
                    return_conflict_count=return_conflicts,
                )
            )
        return sorted(details, key=lambda detail: (detail.arrival_s, detail.request_index))

    def _choose_feeder_return_shuttle(self, placement: PlatterPlacement, reader_unload_done_s: float) -> dict[str, Any]:
        choices = []
        for shuttle in self.shuttles:
            start_s = max(reader_unload_done_s, shuttle.free_s)
            move_to_reader_s = self._move_time_s(
                shuttle.level,
                shuttle.slot,
                self.geometry.reader_level,
                self.geometry.reader_slot,
            )
            move_to_origin_s = self._move_time_s(
                self.geometry.reader_level,
                self.geometry.reader_slot,
                placement.level,
                placement.slot,
            )
            lane_intervals = self._lane_intervals_for_move(
                start_s,
                shuttle.level,
                shuttle.slot,
                self.geometry.reader_level,
                self.geometry.reader_slot,
            )
            lane_intervals.extend(
                self._lane_intervals_for_move(
                    start_s + move_to_reader_s,
                    self.geometry.reader_level,
                    self.geometry.reader_slot,
                    placement.level,
                    placement.slot,
                )
            )
            reader_interval = (start_s + move_to_reader_s, start_s + move_to_reader_s)
            penalty_s, conflict_count = self._conflict_penalty(lane_intervals, reader_interval)
            base_done_s = start_s + move_to_reader_s + move_to_origin_s + self.timing.storage_place_s
            choices.append(
                {
                    "shuttle_id": shuttle.shuttle_id,
                    "base_done_s": base_done_s,
                    "done_s": base_done_s + penalty_s,
                    "conflict_count": conflict_count,
                    "lane_intervals": lane_intervals,
                    "reader_interval": reader_interval,
                }
            )
        return min(choices, key=lambda choice: (choice["done_s"], choice["conflict_count"], choice["shuttle_id"]))

    def _choose_fetch_shuttle(self, placement: PlatterPlacement, reader_ready_s: float) -> dict[str, Any]:
        choices = []
        for shuttle in self.shuttles:
            start_s = max(reader_ready_s, shuttle.free_s)
            move_to_glass_s = self._move_time_s(shuttle.level, shuttle.slot, placement.level, placement.slot)
            move_to_reader_s = self._move_time_s(
                placement.level,
                placement.slot,
                self.geometry.reader_level,
                self.geometry.reader_slot,
            )
            base_duration_s = (
                move_to_glass_s
                + self.timing.storage_pick_s
                + move_to_reader_s
                + self.timing.reader_load_s
            )
            lane_intervals = self._lane_intervals_for_move(
                start_s,
                shuttle.level,
                shuttle.slot,
                placement.level,
                placement.slot,
            )
            reader_arrival_s = start_s + move_to_glass_s + self.timing.storage_pick_s + move_to_reader_s
            lane_intervals.extend(
                self._lane_intervals_for_move(
                    start_s + move_to_glass_s + self.timing.storage_pick_s,
                    placement.level,
                    placement.slot,
                    self.geometry.reader_level,
                    self.geometry.reader_slot,
                )
            )
            reader_interval = (reader_arrival_s, reader_arrival_s + self.timing.reader_load_s)
            penalty_s, conflict_count = self._conflict_penalty(lane_intervals, reader_interval)
            choices.append(
                {
                    "shuttle_id": shuttle.shuttle_id,
                    "base_duration_s": base_duration_s,
                    "done_s": start_s + base_duration_s + penalty_s,
                    "conflict_count": conflict_count,
                    "lane_intervals": lane_intervals,
                    "reader_interval": reader_interval,
                }
            )
        return min(choices, key=lambda choice: (choice["done_s"], choice["conflict_count"], choice["shuttle_id"]))

    def _choose_return_shuttle(self, placement: PlatterPlacement, drive_done_s: float) -> dict[str, Any]:
        choices = []
        for shuttle in self.shuttles:
            start_s = max(drive_done_s, shuttle.free_s)
            move_to_reader_s = self._move_time_s(
                shuttle.level,
                shuttle.slot,
                self.geometry.reader_level,
                self.geometry.reader_slot,
            )
            move_to_origin_s = self._move_time_s(
                self.geometry.reader_level,
                self.geometry.reader_slot,
                placement.level,
                placement.slot,
            )
            lane_intervals = self._lane_intervals_for_move(
                start_s,
                shuttle.level,
                shuttle.slot,
                self.geometry.reader_level,
                self.geometry.reader_slot,
            )
            reader_interval = (
                start_s + move_to_reader_s,
                start_s + move_to_reader_s + self.timing.reader_unload_s,
            )
            lane_intervals.extend(
                self._lane_intervals_for_move(
                    start_s + move_to_reader_s + self.timing.reader_unload_s,
                    self.geometry.reader_level,
                    self.geometry.reader_slot,
                    placement.level,
                    placement.slot,
                )
            )
            penalty_s, conflict_count = self._conflict_penalty(lane_intervals, reader_interval)
            unload_done_s = start_s + move_to_reader_s + self.timing.reader_unload_s + penalty_s
            return_done_s = unload_done_s + move_to_origin_s + self.timing.storage_place_s
            choices.append(
                {
                    "shuttle_id": shuttle.shuttle_id,
                    "move_to_reader_s": move_to_reader_s,
                    "move_to_origin_s": move_to_origin_s,
                    "done_s": return_done_s,
                    "unload_done_s": unload_done_s,
                    "conflict_count": conflict_count,
                    "lane_intervals": lane_intervals,
                    "reader_interval": reader_interval,
                }
            )
        return min(choices, key=lambda choice: (choice["unload_done_s"], choice["done_s"], choice["shuttle_id"]))

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

    def _lane_intervals_for_move(
        self,
        start_s: float,
        src_level: int,
        src_slot: int,
        dst_level: int,
        dst_slot: int,
    ) -> list[tuple[int, float, float]]:
        duration_s = self._move_time_s(src_level, src_slot, dst_level, dst_slot)
        if duration_s <= 0:
            return []
        levels = {src_level, dst_level}
        return [(level, start_s, start_s + duration_s) for level in levels]

    def _conflict_penalty(
        self,
        lane_intervals: list[tuple[int, float, float]],
        reader_interval: tuple[float, float],
    ) -> tuple[float, int]:
        if not self.conflict.enabled:
            return 0.0, 0
        conflicts = 0
        for level, start_s, end_s in lane_intervals:
            if self._has_overlap(self.lane_intervals[level], start_s, end_s):
                conflicts += 1
                break
        if self._has_overlap(self.reader_ingress_intervals, reader_interval[0], reader_interval[1]):
            conflicts += 1
        if conflicts == 0:
            return 0.0, 0
        return self.conflict.penalty_s * conflicts, conflicts

    def _record_intervals(
        self,
        lane_intervals: list[tuple[int, float, float]],
        reader_interval: tuple[float, float],
    ) -> None:
        if not self.conflict.enabled:
            return
        for level, start_s, end_s in lane_intervals:
            self.lane_intervals[level].append((start_s, end_s))
        self.reader_ingress_intervals.append(reader_interval)

    def _has_overlap(self, intervals: list[tuple[float, float]], start_s: float, end_s: float) -> bool:
        if end_s <= start_s:
            return False
        padded_start = start_s - self.conflict.window_s
        padded_end = end_s + self.conflict.window_s
        intervals[:] = [
            (existing_start, existing_end)
            for existing_start, existing_end in intervals
            if existing_end >= padded_start
        ]
        return any(existing_start < padded_end and padded_start < existing_end for existing_start, existing_end in intervals)

    def _place(self, offset: int) -> PlatterPlacement:
        platter_id = _platter_id_for_offset(offset, self.geometry)
        slot_count = self.geometry.levels * self.geometry.slots_per_rack
        mapped_slot = platter_id % slot_count
        level = mapped_slot // self.geometry.slots_per_rack
        slot = mapped_slot % self.geometry.slots_per_rack
        return PlatterPlacement(platter_id=platter_id, level=level, slot=slot)

    def _read_time_s(self, size_bytes: int) -> float:
        return self.timing.reader_mount_s + self.timing.reader_base_s + (size_bytes / MIB) / self.timing.reader_mib_per_s

    def _slot_width_m(self) -> float:
        return self.geometry.rack_length_m / (self.geometry.slots_per_rack - 1)

    def _build_summary(self, details: list[ScalingRequestDetail]) -> dict[str, Any]:
        latencies = [row.latency_s for row in details]
        total_bytes = sum(row.size_bytes for row in details)
        request_count = sum(row.merged_request_count for row in details)
        service_operation_count = len(details)
        merged_request_count = request_count - service_operation_count
        first_arrival_s = details[0].arrival_s if details else 0.0
        last_arrival_s = details[-1].arrival_s if details else 0.0
        last_drive_done_s = max((row.drive_done_s for row in details), default=0.0)
        last_return_done_s = max((row.return_done_s for row in details), default=0.0)
        drive_makespan_s = max(last_drive_done_s - first_arrival_s, 0.0)
        system_drain_s = max(last_return_done_s - first_arrival_s, 0.0)
        reader_load_time_s = service_operation_count * self.timing.reader_load_s
        reader_unload_time_s = sum(row.reader_blocked_by_return_s for row in details)
        reader_pipeline_busy_s = reader_load_time_s + self.reader_busy_s + reader_unload_time_s
        shuttle_utils = [
            shuttle.busy_s / system_drain_s if system_drain_s > 0 else 0.0
            for shuttle in self.shuttles
        ]

        return {
            "config": self.config.to_json_dict(),
            "shuttle_count": self.shuttle_count,
            "request_count": request_count,
            "service_operation_count": service_operation_count,
            "merged_request_count": merged_request_count,
            "ignored_writes": self.input_stats["ignored_writes"],
            "input_rows_scanned": self.input_stats["input_rows_scanned"],
            "arrival_span_s": max(last_arrival_s - first_arrival_s, 0.0),
            "drive_makespan_s": drive_makespan_s,
            "system_drain_s": system_drain_s,
            "throughput_req_per_s": request_count / drive_makespan_s if drive_makespan_s > 0 else 0.0,
            "throughput_mib_per_s": (total_bytes / MIB) / drive_makespan_s if drive_makespan_s > 0 else 0.0,
            "reader_utilization": self.reader_busy_s / drive_makespan_s if drive_makespan_s > 0 else 0.0,
            "reader_load_time_s": reader_load_time_s,
            "reader_unload_time_s": reader_unload_time_s,
            "reader_pipeline_utilization": reader_pipeline_busy_s / drive_makespan_s if drive_makespan_s > 0 else 0.0,
            "shuttle_utilization_avg": mean(shuttle_utils) if shuttle_utils else 0.0,
            "shuttle_utilization_max": max(shuttle_utils, default=0.0),
            "latency_s": _stats(latencies),
            "latency_p50_s": _percentile(sorted(latencies), 0.50) if latencies else 0.0,
            "latency_p95_s": _percentile(sorted(latencies), 0.95) if latencies else 0.0,
            "latency_p99_s": _percentile(sorted(latencies), 0.99) if latencies else 0.0,
            "reader_waiting_for_glass_s": self.reader_waiting_for_glass_s,
            "reader_blocked_by_return_s": self.reader_blocked_by_return_s,
            "feeder_buffer_enabled": self.config.feeder_buffer.enabled,
            "feeder_buffer_slots": self.config.feeder_buffer.slots if self.config.feeder_buffer.enabled else 0,
            "feeder_buffer_wait_for_slot_s": self.feeder_buffer_wait_for_slot_s,
            "feeder_buffer_max_occupancy": self.feeder_buffer_max_occupancy,
            "conflict_count": self.conflict_count,
            "shuttle_utilization": [
                {
                    "id": shuttle.shuttle_id,
                    "busy_s": shuttle.busy_s,
                    "task_count": shuttle.task_count,
                    "utilization": shuttle_utils[shuttle.shuttle_id],
                }
                for shuttle in self.shuttles
            ],
            "assumptions": [
                (
                    "Single reader only; feeder buffer enabled with "
                    f"{self.config.feeder_buffer.slots} slots and no zones. Shuttle holding allowed: "
                    f"{self.config.feeder_buffer.allow_shuttle_holding}. Request merge enabled: {self.config.request_merge}."
                    if self.config.feeder_buffer.enabled
                    else f"Single reader only; no feeder buffer and no zones. Request merge enabled: {self.config.request_merge}."
                ),
                "Global FIFO selects the request; the scheduler chooses the shuttle with earliest delivery.",
                (
                    "In feeder mode, shuttles place glass into the feeder buffer while the reader can keep reading earlier glass."
                    if self.config.feeder_buffer.enabled
                    else "A shuttle can leave after loading glass into the reader."
                ),
                (
                    "Feeder return work is scheduled after fetch work and affects system drain, not drive throughput."
                    if self.config.feeder_buffer.enabled
                    else "Return work does not count toward user latency, but reader accepts the next glass only after unload."
                ),
                "Collision is modeled with coarse lane/reader-ingress penalties, not full MAPF.",
            ],
        }


def _load_read_requests(path: Path, max_requests: int | None) -> tuple[list[WorkRequest], dict[str, int]]:
    requests: list[WorkRequest] = []
    ignored_writes = 0
    input_rows_scanned = 0
    for request in iter_trace(path, None):
        input_rows_scanned += 1
        if request.io_type != "R":
            ignored_writes += 1
            continue
        requests.append(
            WorkRequest(
                index=request.index,
                arrival_s=request.arrival_s,
                io_type=request.io_type,
                lun=request.lun,
                offset=request.offset,
                size_bytes=request.size_bytes,
                observed_response_s=request.observed_response_s,
            )
        )
        if max_requests is not None and len(requests) >= max_requests:
            break
    return requests, {"ignored_writes": ignored_writes, "input_rows_scanned": input_rows_scanned}


def _as_batch_at_t0(requests: list[WorkRequest]) -> list[WorkRequest]:
    return [
        WorkRequest(
            index=request.index,
            arrival_s=0.0,
            io_type=request.io_type,
            lun=request.lun,
            offset=request.offset,
            size_bytes=request.size_bytes,
            observed_response_s=request.observed_response_s,
            merged_request_count=request.merged_request_count,
        )
        for request in requests
    ]


def _merge_requests_by_platter(requests: list[WorkRequest], geometry: GeometryConfig) -> list[WorkRequest]:
    groups: dict[int, list[WorkRequest]] = {}
    for request in requests:
        platter_id = _platter_id_for_offset(request.offset, geometry)
        groups.setdefault(platter_id, []).append(request)

    merged: list[WorkRequest] = []
    for group in groups.values():
        ordered = sorted(group, key=lambda request: (request.arrival_s, request.index))
        first = ordered[0]
        merged.append(
            WorkRequest(
                index=first.index,
                arrival_s=first.arrival_s,
                io_type=first.io_type,
                lun=first.lun,
                offset=first.offset,
                size_bytes=sum(request.size_bytes for request in ordered),
                observed_response_s=first.observed_response_s,
                merged_request_count=sum(request.merged_request_count for request in ordered),
            )
        )

    return sorted(merged, key=lambda request: (request.arrival_s, request.index))


def _platter_id_for_offset(offset: int, geometry: GeometryConfig) -> int:
    if geometry.placement_mode == "offset":
        return offset // geometry.platter_capacity_bytes

    stripe_id = offset // int(geometry.synthetic_stripe_bytes)
    hashed = _hash_u64(stripe_id ^ geometry.synthetic_hash_seed)
    return hashed % int(geometry.synthetic_platter_count)


def _hash_u64(value: int) -> int:
    value &= 0xFFFFFFFFFFFFFFFF
    value ^= value >> 30
    value = (value * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    value ^= value >> 27
    value = (value * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    value ^= value >> 31
    return value


def _write_detail_csv(path: Path, details: list[ScalingRequestDetail]) -> None:
    fieldnames = list(ScalingRequestDetail.__dataclass_fields__.keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in details:
            writer.writerow(row.__dict__)


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"avg": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
    ordered = sorted(values)
    return {
        "avg": mean(ordered),
        "p50": _percentile(ordered, 0.50),
        "p95": _percentile(ordered, 0.95),
        "p99": _percentile(ordered, 0.99),
        "max": ordered[-1],
    }


def _max_buffer_occupancy(intervals: list[tuple[float, float]]) -> int:
    events: list[tuple[float, int]] = []
    for ready_s, leave_s in intervals:
        if leave_s <= ready_s:
            continue
        events.append((ready_s, 1))
        events.append((leave_s, -1))
    occupancy = 0
    max_occupancy = 0
    for _, delta in sorted(events, key=lambda event: (event[0], event[1])):
        occupancy += delta
        max_occupancy = max(max_occupancy, occupancy)
    return max_occupancy


def _percentile(ordered: list[float], quantile: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    position = quantile * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _resolve_path(value: str, base_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()
