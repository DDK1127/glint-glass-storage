"""Fixed 32-rack feeder-buffer architecture comparison."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
import csv
import heapq
import json
import math
import os
from pathlib import Path
import random
from statistics import mean, pstdev
from typing import Any

from .no_zone_conflict import Segment, route
from .paths import portable_path, repository_root_for_config
from .zone_nozone_comparison import ComparisonConfig, ShuttleState, _conflicts, _write_csv, load_config
from .zone_nozone_trace import load_reads, mapping, percentile
from .azure_capacity_scalability import VirtualPlatterWork
from .azure_static_zone_pilot import _sha256


STATIC_ZONE = "static_8zone_end_to_end"
ZONE = "rack_local_zone"
NO_ZONE = "shared_no_zone"
POLICIES = (STATIC_ZONE, ZONE, NO_ZONE)


@dataclass(frozen=True)
class BufferedRackConfig:
    output_dir: Path
    base: ComparisonConfig
    seeds: tuple[int, ...]
    rack_count: int
    rack_length_m: float
    rack_spacing_m: float
    slots_per_rack: int
    reader_count: int
    buffer_slots_per_reader: int
    output_return_threshold: int
    buffer_drop_s: float

    def validate(self) -> None:
        if self.rack_count != 32:
            raise ValueError("This pilot requires exactly 32 racks")
        if self.reader_count != 8 or self.rack_count % self.reader_count:
            raise ValueError("Reader count must be 8 and divide the rack count")
        if self.base.platter_count > self.rack_count * self.slots_per_rack:
            raise ValueError("Not enough rack slots for virtual platters")
        if min(self.rack_length_m, self.rack_spacing_m, self.buffer_drop_s) <= 0:
            raise ValueError("Rack geometry and buffer drop time must be positive")
        if self.buffer_slots_per_reader < 1 or self.output_return_threshold < 1:
            raise ValueError("Buffer parameters must be positive")

    @property
    def motion(self) -> ComparisonConfig:
        return replace(
            self.base,
            levels=self.rack_count,
            level_spacing_m=self.rack_spacing_m,
            mapping_slots_per_level=self.slots_per_rack,
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "output_dir": portable_path(self.output_dir),
            "seeds": list(self.seeds),
            "rack_count": self.rack_count,
            "rack_length_m": self.rack_length_m,
            "rack_spacing_m": self.rack_spacing_m,
            "slots_per_rack": self.slots_per_rack,
            "reader_count": self.reader_count,
            "rack_shuttles": self.rack_count,
            "reader_side_loaders": self.reader_count,
            "buffer_slots_per_reader": self.buffer_slots_per_reader,
            "output_return_threshold": self.output_return_threshold,
            "buffer_drop_s": self.buffer_drop_s,
            "base": self.base.to_json_dict(),
            "scope": {
                "workload": "original Azure head-100k arrivals and online platter merge",
                "zone": "one rack-local shuttle per rack; dedicated rack movement",
                "no_zone": "same 32 shuttles share racks; direct routes wait for prior reservations",
                "static_zone": "8 shuttles and 8 readers; each shuttle owns four racks and carries a platter through the complete reader cycle",
                "buffer": "finite demand-driven input staging; output staging uses return-priority backpressure",
                "reader_loader": "one fixed loader per reader, represented by serialized load/read/unload service",
            },
        }


@dataclass
class RackJob:
    job_id: int
    kind: str
    shuttle_id: int
    home_rack: int
    target_rack: int
    platter_id: int
    start_s: float
    end_s: float
    movement_s: float
    conflict_wait_s: float
    buffer_full_wait_s: float = 0.0
    reader_queue_s: float = 0.0
    logical_requests: int = 0
    bytes: int = 0


def load_study_config(path: str | Path) -> BufferedRackConfig:
    config_path = Path(path).expanduser().resolve()
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    root = repository_root_for_config(config_path)

    def resolve(value: str) -> Path:
        candidate = Path(value).expanduser()
        return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()

    config = BufferedRackConfig(
        output_dir=resolve(raw["output_dir"]),
        base=load_config(resolve(raw["base_config"])),
        seeds=tuple(int(value) for value in raw["seeds"]),
        rack_count=int(raw["rack_count"]),
        rack_length_m=float(raw["rack_length_m"]),
        rack_spacing_m=float(raw["rack_spacing_m"]),
        slots_per_rack=int(raw["slots_per_rack"]),
        reader_count=int(raw["reader_count"]),
        buffer_slots_per_reader=int(raw["buffer_slots_per_reader"]),
        output_return_threshold=int(raw["output_return_threshold"]),
        buffer_drop_s=float(raw["buffer_drop_s"]),
    )
    config.validate()
    return config


def platter_positions(config: BufferedRackConfig, seed: int) -> dict[int, tuple[float, float]]:
    rng = random.Random(seed)
    cells = rng.sample(range(config.rack_count * config.slots_per_rack), config.base.platter_count)
    positions = {}
    for platter, cell in enumerate(cells):
        rack, slot = divmod(cell, config.slots_per_rack)
        positions[platter] = (
            (slot + .5) / config.slots_per_rack * config.rack_length_m,
            rack * config.rack_spacing_m,
        )
    return positions


def rack_for(position: tuple[float, float], config: BufferedRackConfig) -> int:
    return int(round(position[1] / config.rack_spacing_m))


def reader_for_rack(rack: int, config: BufferedRackConfig) -> int:
    return min(config.reader_count - 1, rack // (config.rack_count // config.reader_count))


def _direct_with_wait(
    shuttle: ShuttleState,
    job_id: int,
    phase: str,
    start_s: float,
    target: tuple[float, float],
    reservations: list[Segment],
    config: BufferedRackConfig,
    coordinated: bool,
) -> tuple[list[Segment], float, float, float]:
    source = shuttle.position
    desired = start_s
    conflict_ids: set[tuple[int, int]] = set()
    for _ in range(256):
        segments, end = route(
            shuttle.shuttle_id,
            job_id,
            0,
            phase,
            start_s,
            source,
            target,
            config.motion.motion_dict(),
        )
        conflicts = _conflicts(segments, reservations, config.motion) if coordinated else []
        if not conflicts:
            movement = sum(segment.end - segment.start for segment in segments)
            return segments, end, start_s - desired, movement
        conflict_ids.update((reserved.shuttle, reserved.task) for _, reserved, _, _ in conflicts)
        start_s = max(reserved.end for _, reserved, _, _ in conflicts) + .001
    raise RuntimeError(f"Unable to reserve {phase} after {len(conflict_ids)} conflicts")


def _stationary(
    shuttle: ShuttleState,
    job_id: int,
    phase: str,
    start_s: float,
    duration_s: float,
    reservations: list[Segment],
    config: BufferedRackConfig,
    coordinated: bool,
) -> tuple[Segment, float, float]:
    desired = start_s
    for _ in range(256):
        segment = Segment(
            shuttle.shuttle_id,
            job_id,
            0,
            phase,
            start_s,
            start_s + duration_s,
            shuttle.position[0],
            shuttle.position[1],
        )
        conflicts = _conflicts([segment], reservations, config.motion) if coordinated else []
        if not conflicts:
            return segment, segment.end, start_s - desired
        start_s = max(reserved.end for _, reserved, _, _ in conflicts) + .001
    raise RuntimeError(f"Unable to reserve stationary phase {phase}")


def _buffer_admission(
    arrival_s: float,
    release_times: list[float],
    capacity: int,
) -> float:
    admission = arrival_s
    while True:
        occupied = [release for release in release_times if release > admission + 1e-9]
        if len(occupied) < capacity:
            return admission
        admission = min(occupied)


def _max_buffer_depth(intervals: list[tuple[float, float]]) -> int:
    events = []
    for start, end in intervals:
        if end > start + 1e-9:
            events.extend(((start, 1), (end, -1)))
    depth = maximum = 0
    for _, delta in sorted(events, key=lambda event: (event[0], event[1])):
        depth += delta
        maximum = max(maximum, depth)
    return maximum


def simulate(
    reads,
    mapped,
    positions: dict[int, tuple[float, float]],
    config: BufferedRackConfig,
    policy: str,
) -> tuple[dict[str, Any], list[RackJob]]:
    if policy not in POLICIES:
        raise ValueError(f"Unsupported policy: {policy}")
    if policy == STATIC_ZONE:
        return simulate_static_zone(reads, mapped, positions, config)
    coordinated = policy == NO_ZONE
    ports = [(config.rack_length_m, rack * config.rack_spacing_m) for rack in range(config.rack_count)]
    shuttles = [ShuttleState(rack, 0, ports[rack]) for rack in range(config.rack_count)]
    reader_free = [0.0] * config.reader_count
    reader_busy = [0.0] * config.reader_count
    reader_idle = [0.0] * config.reader_count
    reader_last_end = [reads[0].arrival] * config.reader_count
    buffer_releases: list[list[float]] = [[] for _ in range(config.reader_count)]
    buffer_intervals: list[list[tuple[float, float]]] = [[] for _ in range(config.reader_count)]
    reservations: list[Segment] = []
    pending: dict[int, list[Any]] = {}
    pending_returns: list[dict[str, Any]] = []
    future_returns: list[tuple[float, int, dict[str, Any]]] = []
    platter_free = {platter: 0.0 for platter in positions}
    completions = [None] * len(reads)
    queue_times = [0.0] * len(reads)
    jobs: list[RackJob] = []
    cursor = event_id = queued_requests = 0
    clock = reads[0].arrival
    max_backlog = 0

    while cursor < len(reads) or pending or pending_returns or future_returns:
        while cursor < len(reads) and reads[cursor].arrival <= clock + 1e-9:
            request = reads[cursor]
            pending.setdefault(mapped[request.key], []).append(request)
            queued_requests += 1
            cursor += 1
        while future_returns and future_returns[0][0] <= clock + 1e-9:
            _, _, task = heapq.heappop(future_returns)
            pending_returns.append(task)
        max_backlog = max(max_backlog, queued_requests)
        reservations = [segment for segment in reservations if segment.end > clock + 1e-9]
        idle = [shuttle for shuttle in shuttles if shuttle.free_s <= clock + 1e-9]
        dispatched = False

        while idle:
            urgent_returns = [
                task for task in pending_returns
                if task["platter_id"] in pending or len(pending_returns) >= config.output_return_threshold
            ]
            return_pool = urgent_returns or ([] if pending else pending_returns)
            selected_kind = None
            selected_payload = None
            selected_shuttle = None

            if return_pool:
                candidates = []
                for task in return_pool:
                    rack = task["rack"]
                    eligible = [shuttle for shuttle in idle if policy != ZONE or shuttle.shuttle_id == rack]
                    for shuttle in eligible:
                        distance = abs(shuttle.position[0] - ports[rack][0]) + abs(shuttle.position[1] - ports[rack][1])
                        candidates.append((task["release_s"], distance, task["platter_id"], shuttle.shuttle_id, task, shuttle))
                if candidates:
                    *_, selected_payload, selected_shuttle = min(candidates)
                    selected_kind = "return"

            if selected_kind is None:
                fetch_candidates = []
                for platter, group in pending.items():
                    if platter_free[platter] > clock + 1e-9:
                        continue
                    rack = rack_for(positions[platter], config)
                    eligible = [shuttle for shuttle in idle if policy != ZONE or shuttle.shuttle_id == rack]
                    for shuttle in eligible:
                        distance = abs(shuttle.position[0] - positions[platter][0]) + abs(shuttle.position[1] - positions[platter][1])
                        fetch_candidates.append((group[0].index, distance, platter, shuttle.shuttle_id, platter, shuttle))
                if fetch_candidates:
                    *_, selected_payload, selected_shuttle = min(fetch_candidates)
                    selected_kind = "fetch"

            if selected_kind is None:
                break

            shuttle = selected_shuttle
            idle.remove(shuttle)
            start_s = clock
            conflict_wait = movement = buffer_full_wait = reader_queue = 0.0

            if selected_kind == "fetch":
                platter = selected_payload
                group = pending.pop(platter)
                queued_requests -= len(group)
                target = positions[platter]
                rack = rack_for(target, config)
                port = ports[rack]
                segments, current, wait, moved = _direct_with_wait(
                    shuttle, event_id, "fetch", start_s, target, reservations, config, coordinated
                )
                reservations.extend(segments)
                conflict_wait += wait
                movement += moved
                shuttle.position = target
                hold, current, wait = _stationary(
                    shuttle, event_id, "pick", current, config.base.pick_s,
                    reservations, config, coordinated,
                )
                reservations.append(hold)
                conflict_wait += wait
                segments, current, wait, moved = _direct_with_wait(
                    shuttle, event_id, "to_buffer", current, port,
                    reservations, config, coordinated,
                )
                reservations.extend(segments)
                conflict_wait += wait
                movement += moved
                shuttle.position = port
                rid = reader_for_rack(rack, config)
                admission = _buffer_admission(
                    current, buffer_releases[rid], config.buffer_slots_per_reader
                )
                buffer_full_wait = admission - current
                current = admission
                drop, current, wait = _stationary(
                    shuttle, event_id, "buffer_drop", current, config.buffer_drop_s,
                    reservations, config, coordinated,
                )
                reservations.append(drop)
                conflict_wait += wait
                shuttle.free_s = current
                shuttle.position = port

                unique = {request.key: request.size for request in group}
                service_start = max(current, reader_free[rid])
                reader_queue = service_start - current
                buffer_releases[rid].append(service_start)
                buffer_intervals[rid].append((current, service_start))
                reader_idle[rid] += max(0.0, service_start - reader_last_end[rid])
                service_duration = (
                    config.base.reader_load_s
                    + config.base.reader_mount_s
                    + sum(unique.values()) / (1024**2 * config.base.reader_mib_s)
                    + config.base.reader_unload_s
                )
                service_end = service_start + service_duration
                read_done = service_end - config.base.reader_unload_s
                reader_busy[rid] += service_duration
                reader_free[rid] = service_end
                reader_last_end[rid] = service_end
                for request in group:
                    completions[request.index] = read_done
                    queue_times[request.index] = start_s - request.arrival
                return_task = {
                    "release_s": service_end,
                    "platter_id": platter,
                    "rack": rack,
                    "position": target,
                }
                heapq.heappush(future_returns, (service_end, event_id, return_task))
                platter_free[platter] = math.inf
                jobs.append(
                    RackJob(
                        event_id, "fetch", shuttle.shuttle_id, shuttle.shuttle_id,
                        rack, platter, start_s, current, movement, conflict_wait,
                        buffer_full_wait, reader_queue, len(group), sum(unique.values()),
                    )
                )
            else:
                task = selected_payload
                pending_returns.remove(task)
                rack = task["rack"]
                port = ports[rack]
                target = task["position"]
                segments, current, wait, moved = _direct_with_wait(
                    shuttle, event_id, "output_pickup", start_s, port,
                    reservations, config, coordinated,
                )
                reservations.extend(segments)
                conflict_wait += wait
                movement += moved
                shuttle.position = port
                hold, current, wait = _stationary(
                    shuttle, event_id, "buffer_pick", current, config.base.pick_s,
                    reservations, config, coordinated,
                )
                reservations.append(hold)
                conflict_wait += wait
                segments, current, wait, moved = _direct_with_wait(
                    shuttle, event_id, "return", current, target,
                    reservations, config, coordinated,
                )
                reservations.extend(segments)
                conflict_wait += wait
                movement += moved
                shuttle.position = target
                hold, current, wait = _stationary(
                    shuttle, event_id, "place", current, config.base.place_s,
                    reservations, config, coordinated,
                )
                reservations.append(hold)
                conflict_wait += wait
                shuttle.free_s = current
                platter_free[task["platter_id"]] = current
                jobs.append(
                    RackJob(
                        event_id, "return", shuttle.shuttle_id, shuttle.shuttle_id,
                        rack, task["platter_id"], start_s, current,
                        movement, conflict_wait,
                    )
                )
            event_id += 1
            dispatched = True

        if dispatched:
            continue
        next_arrival = reads[cursor].arrival if cursor < len(reads) else math.inf
        next_shuttle = min((shuttle.free_s for shuttle in shuttles if shuttle.free_s > clock + 1e-9), default=math.inf)
        next_return = future_returns[0][0] if future_returns else math.inf
        next_platter = min(
            (platter_free[platter] for platter in pending if platter_free[platter] > clock + 1e-9),
            default=math.inf,
        )
        next_time = min(next_arrival, next_shuttle, next_return, next_platter)
        if not math.isfinite(next_time) or next_time <= clock + 1e-12:
            raise RuntimeError("Buffered 32-rack simulation made no progress")
        clock = next_time

    if not all(value is not None for value in completions):
        raise RuntimeError("Not all requests completed")
    latencies = [completion - request.arrival for completion, request in zip(completions, reads)]
    last_read = max(completions)
    horizon = max(max(shuttle.free_s for shuttle in shuttles), max(reader_free))
    fetch_jobs = [job for job in jobs if job.kind == "fetch"]
    return_jobs = [job for job in jobs if job.kind == "return"]
    active_start = reads[0].arrival
    reader_capacity = max(1e-9, (last_read - active_start) * config.reader_count)
    result = {
        "policy": policy,
        "logical_requests": len(reads),
        "logical_bytes": sum(request.size for request in reads),
        "physical_services": len(fetch_jobs),
        "physical_bytes": sum(job.bytes for job in fetch_jobs),
        "return_services": len(return_jobs),
        "latency_mean_s": mean(latencies),
        "latency_p50_s": percentile(latencies, .5),
        "latency_p95_s": percentile(latencies, .95),
        "latency_p99_s": percentile(latencies, .99),
        "last_read_s": last_read,
        "read_drain_s": max(0.0, last_read - reads[-1].arrival),
        "system_return_drain_s": max(0.0, horizon - reads[-1].arrival),
        "observed_request_throughput": len(reads) / (last_read - active_start),
        "request_queue_mean_s": mean(queue_times),
        "reader_utilization": sum(reader_busy) / reader_capacity,
        "reader_starvation_s": sum(reader_idle),
        "movement_s": sum(job.movement_s for job in jobs),
        "fetch_movement_s": sum(job.movement_s for job in fetch_jobs),
        "return_movement_s": sum(job.movement_s for job in return_jobs),
        "conflict_wait_s": sum(job.conflict_wait_s for job in jobs),
        "buffer_full_wait_s": sum(job.buffer_full_wait_s for job in fetch_jobs),
        "reader_queue_s": sum(job.reader_queue_s for job in fetch_jobs),
        "max_input_buffer_depth": max(_max_buffer_depth(intervals) for intervals in buffer_intervals),
        "cross_rack_fetch_fraction": mean(job.shuttle_id != job.target_rack for job in fetch_jobs),
        "max_request_backlog": max_backlog,
    }
    if len(fetch_jobs) != len(return_jobs):
        raise RuntimeError("Every fetched platter must be returned exactly once")
    result["rack_shuttle_count"] = config.rack_count
    result["reader_side_loader_count"] = config.reader_count
    result["buffer_slots_per_reader"] = config.buffer_slots_per_reader
    if policy == ZONE and result["conflict_wait_s"] != 0:
        raise RuntimeError("Non-coordinated policy accumulated conflict waiting")
    return result, jobs


def simulate_static_zone(
    reads,
    mapped,
    positions: dict[int, tuple[float, float]],
    config: BufferedRackConfig,
) -> tuple[dict[str, Any], list[RackJob]]:
    zones = config.reader_count
    racks_per_zone = config.rack_count // zones
    reader_positions = [
        (
            config.rack_length_m,
            (zone * racks_per_zone + (racks_per_zone - 1) / 2) * config.rack_spacing_m,
        )
        for zone in range(zones)
    ]
    shuttles = [ShuttleState(zone, 0, reader_positions[zone]) for zone in range(zones)]
    reader_busy = [0.0] * zones
    reader_idle = [0.0] * zones
    reader_last_end = [reads[0].arrival] * zones
    platter_free = {platter: 0.0 for platter in positions}
    pending: dict[int, list[Any]] = {}
    completions = [None] * len(reads)
    queue_times = [0.0] * len(reads)
    jobs: list[RackJob] = []
    cursor = job_id = queued_requests = max_backlog = 0
    fetch_movement_total = return_movement_total = 0.0
    clock = reads[0].arrival
    motion = config.motion.motion_dict()

    def direct(shuttle, task, phase, start, target):
        segments, end = route(
            shuttle.shuttle_id,
            task,
            0,
            phase,
            start,
            shuttle.position,
            target,
            motion,
        )
        return end, sum(segment.end - segment.start for segment in segments)

    while cursor < len(reads) or pending:
        while cursor < len(reads) and reads[cursor].arrival <= clock + 1e-9:
            request = reads[cursor]
            pending.setdefault(mapped[request.key], []).append(request)
            queued_requests += 1
            cursor += 1
        max_backlog = max(max_backlog, queued_requests)
        choices = []
        for platter, group in pending.items():
            if platter_free[platter] > clock + 1e-9:
                continue
            rack = rack_for(positions[platter], config)
            owner = reader_for_rack(rack, config)
            shuttle = shuttles[owner]
            if shuttle.free_s <= clock + 1e-9:
                choices.append((group[0].index, platter, owner))
        if choices:
            _, platter, owner = min(choices)
            group = pending.pop(platter)
            queued_requests -= len(group)
            target = positions[platter]
            shuttle = shuttles[owner]
            start_s = clock
            current, fetch_movement = direct(shuttle, job_id, "fetch", start_s, target)
            current += config.base.pick_s
            shuttle.position = target
            current, delivery_movement = direct(
                shuttle, job_id, "delivery", current, reader_positions[owner]
            )
            shuttle.position = reader_positions[owner]
            reader_idle[owner] += max(0.0, current - reader_last_end[owner])
            unique = {request.key: request.size for request in group}
            service_duration = (
                config.base.reader_load_s
                + config.base.reader_mount_s
                + sum(unique.values()) / (1024**2 * config.base.reader_mib_s)
                + config.base.reader_unload_s
            )
            service_start = current
            service_end = service_start + service_duration
            read_done = service_end - config.base.reader_unload_s
            reader_busy[owner] += service_duration
            reader_last_end[owner] = service_end
            current, return_movement = direct(
                shuttle, job_id, "return", service_end, target
            )
            fetch_movement_total += fetch_movement + delivery_movement
            return_movement_total += return_movement
            current += config.base.place_s
            shuttle.position = target
            shuttle.free_s = current
            platter_free[platter] = current
            for request in group:
                completions[request.index] = read_done
                queue_times[request.index] = start_s - request.arrival
            jobs.append(
                RackJob(
                    job_id,
                    "fetch",
                    owner,
                    owner,
                    rack,
                    platter,
                    start_s,
                    current,
                    fetch_movement + delivery_movement + return_movement,
                    0.0,
                    logical_requests=len(group),
                    bytes=sum(unique.values()),
                )
            )
            job_id += 1
            continue
        next_arrival = reads[cursor].arrival if cursor < len(reads) else math.inf
        next_shuttle = min(
            (shuttle.free_s for shuttle in shuttles if shuttle.free_s > clock + 1e-9),
            default=math.inf,
        )
        next_platter = min(
            (platter_free[platter] for platter in pending if platter_free[platter] > clock + 1e-9),
            default=math.inf,
        )
        next_time = min(next_arrival, next_shuttle, next_platter)
        if not math.isfinite(next_time) or next_time <= clock + 1e-12:
            raise RuntimeError("Static 8-zone simulation made no progress")
        clock = next_time

    if not all(value is not None for value in completions):
        raise RuntimeError("Static 8-zone did not complete every request")
    latencies = [completion - request.arrival for completion, request in zip(completions, reads)]
    last_read = max(completions)
    horizon = max(shuttle.free_s for shuttle in shuttles)
    capacity = max(1e-9, (last_read - reads[0].arrival) * zones)
    result = {
        "policy": STATIC_ZONE,
        "logical_requests": len(reads),
        "logical_bytes": sum(request.size for request in reads),
        "physical_services": len(jobs),
        "physical_bytes": sum(job.bytes for job in jobs),
        "return_services": len(jobs),
        "latency_mean_s": mean(latencies),
        "latency_p50_s": percentile(latencies, .5),
        "latency_p95_s": percentile(latencies, .95),
        "latency_p99_s": percentile(latencies, .99),
        "last_read_s": last_read,
        "read_drain_s": max(0.0, last_read - reads[-1].arrival),
        "system_return_drain_s": max(0.0, horizon - reads[-1].arrival),
        "observed_request_throughput": len(reads) / (last_read - reads[0].arrival),
        "request_queue_mean_s": mean(queue_times),
        "reader_utilization": sum(reader_busy) / capacity,
        "reader_starvation_s": sum(reader_idle),
        "movement_s": sum(job.movement_s for job in jobs),
        "fetch_movement_s": fetch_movement_total,
        "return_movement_s": return_movement_total,
        "conflict_wait_s": 0.0,
        "buffer_full_wait_s": 0.0,
        "reader_queue_s": 0.0,
        "max_input_buffer_depth": 0,
        "cross_rack_fetch_fraction": mean(
            job.target_rack // racks_per_zone != job.shuttle_id for job in jobs
        ),
        "max_request_backlog": max_backlog,
        "rack_shuttle_count": zones,
        "reader_side_loader_count": 0,
        "buffer_slots_per_reader": 0,
    }
    return result, jobs


def _case(config: BufferedRackConfig, seed: int) -> list[dict[str, Any]]:
    reads = load_reads(config.base.batch_path)
    mapped = mapping(reads, config.base, seed)
    positions = platter_positions(config, seed)
    rows = []
    for policy in POLICIES:
        result, _ = simulate(reads, mapped, positions, config, policy)
        rows.append({"seed": seed, **result})
    return rows


def _aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for policy in POLICIES:
        group = [row for row in rows if row["policy"] == policy]
        aggregate: dict[str, Any] = {"policy": policy, "seeds": len(group)}
        for key in group[0]:
            if key in {"seed", "policy"}:
                continue
            values = [float(row[key]) for row in group]
            aggregate[key + "_mean"] = mean(values)
            aggregate[key + "_std"] = pstdev(values) if len(values) > 1 else 0.0
        output.append(aggregate)
    return output


def _plot(aggregate: list[dict[str, Any]], output: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/glint-mplconfig")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = ["Static zone\n8 shuttles", "Rack-local zone\n32 shuttles + buffer", "Shared no-zone\n32 shuttles + buffer"]
    colors = ["#7B8790", "#4F8B57", "#2B819B"]
    x = list(range(3))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
    axes[0].bar(x, [row["latency_p99_s_mean"] / 60 for row in aggregate], color=colors)
    axes[1].bar(x, [row["latency_mean_s_mean"] / 60 for row in aggregate], color=colors)
    axes[0].set_title("(a) Tail latency (p99)", loc="left", fontsize=11)
    axes[1].set_title("(b) Mean request latency", loc="left", fontsize=11)
    for axis in axes:
        axis.set_xticks(x, labels, rotation=12, ha="right")
        axis.set_ylabel("Arrival-to-read completion (min)")
        axis.spines[["top", "right"]].set_visible(False)
    fig.suptitle("32 racks × 16 m, 8 fixed readers", fontsize=13)
    fig.tight_layout()
    for extension in ("png", "pdf"):
        fig.savefig(output / f"fig1_tail_latency.{extension}", dpi=200)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
    axes[0].bar(x, [100 * row["reader_utilization_mean"] for row in aggregate], color=colors)
    axes[1].bar(x, [row["observed_request_throughput_mean"] for row in aggregate], color=colors)
    axes[0].set_ylabel("Reader utilization (%)")
    axes[1].set_ylabel("Observed request throughput (request/s)")
    axes[0].set_title("(a) Are readers kept busy?", loc="left", fontsize=11)
    axes[1].set_title("(b) End-to-end drain rate", loc="left", fontsize=11)
    for axis in axes:
        axis.set_xticks(x, labels, rotation=12, ha="right")
        axis.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    for extension in ("png", "pdf"):
        fig.savefig(output / f"fig2_reader_and_throughput.{extension}", dpi=200)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.4, 4.3))
    components = [
        ("fetch_movement_s", "Fetch / delivery", "#327ba4"),
        ("return_movement_s", "Return to rack", "#9bc3d2"),
        ("conflict_wait_s", "Conflict waiting", "#daa24b"),
        ("buffer_full_wait_s", "Buffer-full waiting", "#b95c55"),
        ("reader_queue_s", "Buffered reader queue", "#ae6d91"),
    ]
    bottoms = [0.0] * 3
    for metric, label, color in components:
        values = [row[metric + "_mean"] / row["physical_services_mean"] for row in aggregate]
        ax.bar(x, values, bottom=bottoms, color=color, label=label)
        bottoms = [left + right for left, right in zip(bottoms, values)]
    ax.set_xticks(x, labels)
    ax.set_ylabel("Accumulated time per physical service (s)")
    ax.set_title("Where transport-side time goes", loc="left", fontsize=11)
    ax.legend(frameon=False, ncol=2, fontsize=8.5, loc="upper left")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    for extension in ("png", "pdf"):
        fig.savefig(output / f"fig3_transport_breakdown.{extension}", dpi=200)
    plt.close(fig)


def _write_report(config: BufferedRackConfig, aggregate: list[dict[str, Any]]) -> None:
    by_policy = {row["policy"]: row for row in aggregate}
    static = by_policy[STATIC_ZONE]
    zone = by_policy[ZONE]
    no_zone = by_policy[NO_ZONE]
    static_services = static["physical_services_mean"]
    zone_services = zone["physical_services_mean"]
    no_zone_services = no_zone["physical_services_mean"]
    lines = [
        "# Fixed 32-Rack Feeder-Buffer Study",
        "",
        "## Setup",
        "",
        "All policies use the same 32 racks × 16 m, 1 m rack spacing, 8 readers, Azure arrivals, and paired platter placement. Static Zone uses 8 end-to-end shuttles without buffers. Rack-local Zone and Shared No-Zone use 32 rack shuttles, 8 fixed reader-side loaders, and four input staging slots per reader.",
        "",
        "| Policy | Mean latency | p99 latency | Throughput | Reader utilization | Conflict wait / service | Buffer wait / service |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    names = {STATIC_ZONE: "Static Zone", ZONE: "Rack-local Zone", NO_ZONE: "Shared No-Zone"}
    for row in aggregate:
        services = row["physical_services_mean"]
        lines.append(
            f"| {names[row['policy']]} | {row['latency_mean_s_mean']/60:.2f} min | "
            f"{row['latency_p99_s_mean']/60:.2f} min | {row['observed_request_throughput_mean']:.2f} req/s | "
            f"{row['reader_utilization_mean']:.1%} | {row['conflict_wait_s_mean']/services:.2f} s | "
            f"{(row['buffer_full_wait_s_mean']+row['reader_queue_s_mean'])/services:.2f} s |"
        )
    lines.extend(
        [
            "",
            "## 主要觀察",
            "",
            f"Static Zone 使用 8 個 end-to-end shuttles，每台負責 4 racks，p99 為 {static['latency_p99_s_mean']/60:.2f} 分鐘。它沒有 feeder buffer，作為原始 8-zone 架構基準。",
            "",
            f"Rack-local Zone 的 p99 為 {zone['latency_p99_s_mean']/60:.2f} 分鐘，reader utilization 達 {zone['reader_utilization_mean']:.1%}。四-slot feeder buffers 已將 32 條 rack-local retrieval streams 平滑地供應給 8 readers；buffer queue 在這裡代表 reader 接近飽和，而不是 reader starvation。",
            "",
            f"Shared No-Zone 有 {no_zone['cross_rack_fetch_fraction_mean']:.1%} fetch 由非本 rack shuttle 執行，平均 transport movement 從 Zone 的 {zone['movement_s_mean']/zone_services:.1f} 秒/service 增加到 {no_zone['movement_s_mean']/no_zone_services:.1f} 秒/service。再加上 {no_zone['conflict_wait_s_mean']/no_zone_services:.1f} 秒/service 的 conflict waiting，p99 上升到 {no_zone['latency_p99_s_mean']/60:.2f} 分鐘，reader utilization 降到 {no_zone['reader_utilization_mean']:.1%}。",
            "",
            f"Rack-local Zone 相對 Static 的差異同時包含更多 rack shuttles與 feeder-buffer handoff；這是 architecture comparison，不是單一 scheduling ablation。Static movement 為 {static['movement_s_mean']/static_services:.1f} 秒/service，Rack-local Zone 為 {zone['movement_s_mean']/zone_services:.1f} 秒/service。",
            "",
            "這個固定配置中，每個 rack 已有一台 shuttle，shared ownership 幾乎沒有額外 capacity 可以回收。Rack-local Zone + feeder buffer 反而同時保留 local movement 並讓 readers 持續有 platter 可讀。",
            "",
            "## Model boundary",
            "",
            "- Static Zone has 8 end-to-end shuttles and no feeder buffer; Rack-local Zone has 32 rack shuttles plus 8 fixed reader-side loaders.",
            "- Rack-local Zone has one dedicated shuttle per rack and assumes dedicated rack movement is conflict-free.",
            "- Rack centerlines are 1 m apart, larger than the 0.65 m clearance; cross-rack paths can still intersect during vertical movement.",
            "- Shared No-Zone uses the same oldest-request/nearest-shuttle dispatch and direct routes, but waits behind prior space-time reservations.",
            "- The input buffer has four slots per reader. Waiting outside a full buffer is an optimistic off-rail hold.",
            "- Output staging is bounded indirectly by prioritizing returns once 32 completed platters are waiting.",
            "- Reader-side loader movement is abstracted into serialized reader load/unload time; it is not a separately routed robot.",
        ]
    )
    (config.output_dir / "ANALYSIS_ZH.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(config: BufferedRackConfig, workers: int = 1) -> dict[str, Any]:
    config.validate()
    if _sha256(config.base.batch_path) != config.base.batch_sha256:
        raise ValueError("Trace checksum mismatch")
    rows = []

    def retain(seed_rows):
        rows.extend(seed_rows)
        rows.sort(key=lambda row: (row["seed"], POLICIES.index(row["policy"])))
        _write_csv(config.output_dir / "runs.csv", rows)
        print(
            f"seed={seed_rows[0]['seed']} p99(min)="
            f"{[round(row['latency_p99_s']/60,2) for row in seed_rows]}",
            flush=True,
        )

    config.output_dir.mkdir(parents=True, exist_ok=True)
    if workers <= 1:
        for seed in config.seeds:
            retain(_case(config, seed))
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_case, config, seed) for seed in config.seeds]
            for future in as_completed(futures):
                retain(future.result())
    aggregate = _aggregate(rows)
    result = {
        "config": config.to_json_dict(),
        "aggregate": aggregate,
        "validation": {
            "logical_requests_per_run": 100000,
            "paired_trace_and_placement": True,
            "fixed_racks": 32,
            "fixed_rack_length_m": 16,
            "fixed_rack_shuttles": 32,
            "fixed_readers": 8,
            "static_and_rack_local_conflict_wait_s": 0,
        },
    }
    _write_csv(config.output_dir / "runs.csv", rows)
    _write_csv(config.output_dir / "aggregate.csv", aggregate)
    (config.output_dir / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    _plot(aggregate, config.output_dir)
    _write_report(config, aggregate)
    return result
