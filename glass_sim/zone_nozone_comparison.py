"""Paired static-zone and coordinated no-zone trace-derived comparison."""
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

from .azure_capacity_scalability import VirtualPlatterWork, build_virtual_platter_work
from .azure_static_zone_pilot import _load_batch, _sha256
from .no_zone_conflict import (
    Segment,
    close_intervals,
    exposure,
    route,
    validate_config,
)
from .paths import portable_path, repository_root_for_config


STATIC_ZONE = "static_zone"
NO_ZONE = "no_zone_coordinated"
NO_ZONE_CBS = "no_zone_windowed_cbs"
NO_ZONE_VIRTUAL = "no_zone_virtual_ideal"
POLICIES = (STATIC_ZONE, NO_ZONE)


@dataclass(frozen=True)
class ComparisonConfig:
    output_dir: Path
    batch_path: Path
    batch_sha256: str
    seeds: tuple[int, ...]
    lengths_m: tuple[float, ...]
    platter_count: int
    levels: int
    mapping_slots_per_level: int
    level_spacing_m: float
    speed_m_s: float
    acceleration_m_s2: float
    crab_s_per_level: float
    clearance_x_m: float
    clearance_y_m: float
    pick_s: float
    place_s: float
    reader_load_s: float
    reader_unload_s: float
    reader_mount_s: float
    reader_mib_s: float

    def motion_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in asdict(self).items()
            if key
            not in {
                "output_dir",
                "batch_path",
                "batch_sha256",
                "seeds",
                "lengths_m",
            }
        } | {
            "seeds": list(self.seeds),
            "lengths_m": list(self.lengths_m),
            "penalty_s": {
                "head_on": 0,
                "same_direction": 0,
                "moving_vs_stopped": 0,
                "stopped_vs_stopped": 0,
                "crossing_or_crabbing": 0,
            },
            "penalty_multipliers": [0],
        }

    def validate(self) -> None:
        if not self.batch_path.is_file():
            raise ValueError(f"Missing batch: {self.batch_path}")
        if len(self.batch_sha256) != 64:
            raise ValueError("batch_sha256 must contain 64 hexadecimal characters")
        try:
            int(self.batch_sha256, 16)
        except ValueError as exc:
            raise ValueError("batch_sha256 must be hexadecimal") from exc
        validate_config(self.motion_dict())

    def to_json_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["output_dir"] = portable_path(self.output_dir)
        result["batch_path"] = portable_path(self.batch_path)
        result["seeds"] = list(self.seeds)
        result["lengths_m"] = list(self.lengths_m)
        result["scope"] = {
            "trace_semantics": "Azure identity, bytes, reuse, and natural request order",
            "arrival_model": "closed batch; original interarrival times are not replayed",
            "merge": "batch-wide virtual-platter merge",
            "placement": "seeded synthetic physical placement paired across policies",
            "static_conflicts": "zero by strict non-overlapping-zone construction",
            "no_zone_wait": "safe holding-pocket delay feeds back into dispatch",
            "no_zone_bypass": "candidate intermediate levels; earliest safe completion wins",
        }
        return result


@dataclass
class ShuttleState:
    shuttle_id: int
    side: int
    position: tuple[float, float]
    free_s: float = 0.0
    active_s: float = 0.0
    holding_s: float = 0.0
    detour_s: float = 0.0
    conflict_count: int = 0


@dataclass
class ScheduledJob:
    task_id: int
    shuttle_id: int
    reader_id: int
    zone_id: int
    start_s: float
    end_s: float
    base_cycle_s: float
    actual_cycle_s: float
    conflict_wait_s: float
    detour_s: float
    conflict_count: int
    reader_queue_s: float
    fetch_direct_s: float
    delivery_direct_s: float
    return_direct_s: float
    reader_service_s: float
    pick_place_s: float
    fetch_coordination_s: float
    pick_coordination_s: float
    delivery_coordination_s: float
    reader_coordination_s: float
    return_coordination_s: float
    place_coordination_s: float
    size_bytes: int
    logical_requests: int


def load_config(path: str | Path) -> ComparisonConfig:
    config_path = Path(path).expanduser().resolve()
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    root = repository_root_for_config(config_path)

    def resolve(value: str) -> Path:
        candidate = Path(value).expanduser()
        return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()

    config = ComparisonConfig(
        output_dir=resolve(raw["output_dir"]),
        batch_path=resolve(raw["batch_path"]),
        batch_sha256=str(raw["batch_sha256"]).lower(),
        seeds=tuple(int(value) for value in raw["seeds"]),
        lengths_m=tuple(float(value) for value in raw["lengths_m"]),
        **{
            key: raw[key]
            for key in (
                "platter_count",
                "levels",
                "mapping_slots_per_level",
                "level_spacing_m",
                "speed_m_s",
                "acceleration_m_s2",
                "crab_s_per_level",
                "clearance_x_m",
                "clearance_y_m",
                "pick_s",
                "place_s",
                "reader_load_s",
                "reader_unload_s",
                "reader_mount_s",
                "reader_mib_s",
            )
        },
    )
    config.validate()
    return config


def physical_positions(
    work: list[VirtualPlatterWork],
    config: ComparisonConfig,
    seed: int,
    length_m: float,
) -> dict[int, tuple[int, float, float]]:
    rng = random.Random(seed)
    cells = rng.sample(
        range(2 * config.levels * config.mapping_slots_per_level),
        len(work),
    )
    positions = {}
    ordered = sorted(work, key=lambda item: item.virtual_platter_id)
    for item, cell in zip(ordered, cells):
        side, local = divmod(
            cell,
            config.levels * config.mapping_slots_per_level,
        )
        level, slot = divmod(local, config.mapping_slots_per_level)
        positions[item.virtual_platter_id] = (
            side,
            (slot + 0.5) / config.mapping_slots_per_level * length_m,
            level * config.level_spacing_m,
        )
    return positions


def reader_positions(config: ComparisonConfig) -> list[tuple[int, float, float]]:
    return [
        (side, 0.0, level * config.level_spacing_m)
        for side in (0, 1)
        for level in (1, 3, 5, 7)
    ]


def zone_for(position: tuple[int, float, float], config: ComparisonConfig) -> int:
    side, _, y = position
    level = min(config.levels - 1, int(round(y / config.level_spacing_m)))
    return side * 4 + level // 2


def _shift(segments: list[Segment], delta: float) -> list[Segment]:
    return [
        Segment(
            shuttle=segment.shuttle,
            task=segment.task,
            side=segment.side,
            phase=segment.phase,
            start=segment.start + delta,
            end=segment.end + delta,
            x=segment.x,
            y=segment.y,
            vx=segment.vx,
            vy=segment.vy,
            ax=segment.ax,
            ay=segment.ay,
        )
        for segment in segments
    ]


def _path_via_level(
    shuttle_id: int,
    task_id: int,
    side: int,
    phase: str,
    start_s: float,
    source: tuple[float, float],
    target: tuple[float, float],
    level_y: float | None,
    motion: dict[str, Any],
) -> tuple[list[Segment], float]:
    if level_y is None:
        return route(
            shuttle_id,
            task_id,
            side,
            phase,
            start_s,
            source,
            target,
            motion,
        )
    first, time = route(
        shuttle_id,
        task_id,
        side,
        phase,
        start_s,
        source,
        (source[0], level_y),
        motion,
    )
    second, time = route(
        shuttle_id,
        task_id,
        side,
        phase,
        time,
        (source[0], level_y),
        (target[0], level_y),
        motion,
    )
    third, time = route(
        shuttle_id,
        task_id,
        side,
        phase,
        time,
        (target[0], level_y),
        target,
        motion,
    )
    return first + second + third, time


def _conflicts(
    candidate: list[Segment],
    reservations: list[Segment],
    config: ComparisonConfig,
) -> list[tuple[Segment, Segment, float, float]]:
    conflicts = []
    for segment in candidate:
        for reserved in reservations:
            if (segment.side != reserved.side or segment.shuttle == reserved.shuttle
                    or reserved.end <= segment.start or reserved.start >= segment.end):
                continue
            for start, end in close_intervals(
                segment,
                reserved,
                config.clearance_x_m,
                config.clearance_y_m,
            ):
                conflicts.append((segment, reserved, start, end))
    return conflicts


def plan_route(
    shuttle_id: int,
    task_id: int,
    side: int,
    phase: str,
    desired_start_s: float,
    source: tuple[float, float],
    target: tuple[float, float],
    reservations: list[Segment],
    config: ComparisonConfig,
    coordinated: bool,
) -> tuple[list[Segment], float, float, float, int]:
    motion = config.motion_dict()
    direct, direct_end = _path_via_level(
        shuttle_id,
        task_id,
        side,
        phase,
        desired_start_s,
        source,
        target,
        None,
        motion,
    )
    direct_duration = direct_end - desired_start_s
    if not coordinated:
        return direct, direct_end, 0.0, 0.0, 0

    initial_conflicts = _conflicts(direct, reservations, config)
    if not initial_conflicts:
        return direct, direct_end, 0.0, 0.0, 0

    lane_candidates: list[float | None] = [None]
    lane_candidates.extend(
        level * config.level_spacing_m for level in range(config.levels)
    )
    options = []
    for lane_y in lane_candidates:
        start = desired_start_s
        conflict_ids: set[tuple[int, int]] = {
            (reserved.shuttle, reserved.task)
            for _, reserved, _, _ in initial_conflicts
        }
        for _ in range(256):
            candidate, end = _path_via_level(
                shuttle_id,
                task_id,
                side,
                phase,
                start,
                source,
                target,
                lane_y,
                motion,
            )
            conflicts = _conflicts(candidate, reservations, config)
            if not conflicts:
                duration = end - start
                options.append(
                    (
                        end,
                        start - desired_start_s,
                        max(0.0, duration - direct_duration),
                        len(conflict_ids),
                        lane_y is not None,
                        candidate,
                    )
                )
                break
            conflict_ids.update(
                (reserved.shuttle, reserved.task)
                for _, reserved, _, _ in conflicts
            )
            start += max(max(0.001, reserved.end - segment.start)
                         for segment, reserved, _, _ in conflicts)
        else:
            raise RuntimeError("Unable to find a conflict-free route")
    if not options:
        raise RuntimeError("No route candidate")
    end, wait, detour, count, _, segments = min(
        options,
        key=lambda option: (
            option[0],
            option[1],
            option[2],
            option[4],
        ),
    )
    return segments, end, wait, detour, count


def _hold(
    shuttle_id: int,
    task_id: int,
    side: int,
    phase: str,
    desired_start_s: float,
    duration_s: float,
    position: tuple[float, float],
    reservations: list[Segment],
    config: ComparisonConfig,
    coordinated: bool,
) -> tuple[Segment, float, float, int]:
    start = desired_start_s
    conflicts_seen: set[tuple[int, int]] = set()
    for _ in range(256):
        segment = Segment(
            shuttle_id,
            task_id,
            side,
            phase,
            start,
            start + duration_s,
            position[0],
            position[1],
        )
        conflicts = _conflicts([segment], reservations, config) if coordinated else []
        if not conflicts:
            return segment, segment.end, start - desired_start_s, len(conflicts_seen)
        conflicts_seen.update(
            (reserved.shuttle, reserved.task)
            for _, reserved, _, _ in conflicts
        )
        start = max(reserved.end for _, reserved, _, _ in conflicts) + 0.001
    raise RuntimeError("Unable to schedule stationary operation")


def _pocket_wait(
    shuttle_id: int,
    task_id: int,
    start_s: float,
    end_s: float,
    position: tuple[float, float],
) -> list[Segment]:
    if end_s <= start_s + 1e-12:
        return []
    return [
        Segment(
            shuttle_id,
            task_id,
            -1,
            "holding_pocket",
            start_s,
            end_s,
            position[0],
            position[1],
        )
    ]


def _direct_duration(
    shuttle_id: int,
    task_id: int,
    side: int,
    phase: str,
    source: tuple[float, float],
    target: tuple[float, float],
    config: ComparisonConfig,
) -> float:
    _, end = _path_via_level(
        shuttle_id,
        task_id,
        side,
        phase,
        0.0,
        source,
        target,
        None,
        config.motion_dict(),
    )
    return end


def schedule_job(
    work: VirtualPlatterWork,
    position: tuple[int, float, float],
    shuttle: ShuttleState,
    readers: list[tuple[int, float, float]],
    reader_free: list[float],
    reservations: list[Segment],
    config: ComparisonConfig,
    policy: str,
    reader_id_override: int | None = None,
) -> tuple[ScheduledJob, list[Segment]]:
    coordinated = policy in {NO_ZONE, NO_ZONE_CBS}
    side, x, y = position
    task_id = work.virtual_platter_id
    start_s = shuttle.free_s
    source = shuttle.position
    platter = (x, y)
    local_segments: list[Segment] = []
    conflict_wait_s = 0.0
    detour_s = 0.0
    conflict_count = 0

    fetch, fetch_end, wait, detour, conflicts = plan_route(
        shuttle.shuttle_id,
        task_id,
        side,
        "fetch",
        start_s,
        source,
        platter,
        reservations,
        config,
        coordinated,
    )
    actual_fetch_start = fetch[0].start if fetch else start_s
    local_segments.extend(
        _pocket_wait(
            shuttle.shuttle_id,
            task_id,
            start_s,
            actual_fetch_start,
            source,
        )
    )
    local_segments.extend(fetch)
    fetch_wait_s = wait
    fetch_detour_s = detour
    conflict_wait_s += wait
    detour_s += detour
    conflict_count += conflicts

    pick, pick_end, wait, conflicts = _hold(
        shuttle.shuttle_id,
        task_id,
        side,
        "pick",
        fetch_end,
        config.pick_s,
        platter,
        reservations + local_segments,
        config,
        coordinated,
    )
    local_segments.extend(
        _pocket_wait(
            shuttle.shuttle_id,
            task_id,
            fetch_end,
            pick.start,
            platter,
        )
    )
    local_segments.append(pick)
    pick_wait_s = wait
    conflict_wait_s += wait
    conflict_count += conflicts

    if reader_id_override is not None:
        if readers[reader_id_override][0] != side:
            raise ValueError("Reader override must remain on the platter side")
        reader_id = reader_id_override
    elif policy == STATIC_ZONE:
        reader_id = zone_for(position, config)
    elif policy in {NO_ZONE_CBS, NO_ZONE_VIRTUAL}:
        read_duration = (
            config.reader_load_s
            + config.reader_mount_s
            + work.size_bytes / (1024**2 * config.reader_mib_s)
            + config.reader_unload_s
        )
        reader_id = min(
            (
                index
                for index, reader in enumerate(readers)
                if reader[0] == side
            ),
            key=lambda index: (
                max(
                    pick_end
                    + _direct_duration(
                        shuttle.shuttle_id,
                        task_id,
                        side,
                        "delivery",
                        platter,
                        readers[index][1:],
                        config,
                    ),
                    reader_free[index],
                )
                + read_duration,
                index,
            ),
        )
    else:
        reader_id = min(
            (
                index
                for index, reader in enumerate(readers)
                if reader[0] == side
            ),
            key=lambda index: (
                abs(readers[index][1] - x)
                + abs(readers[index][2] - y),
                reader_free[index],
                index,
            ),
        )
    reader_position = readers[reader_id][1:]
    delivery, delivery_end, wait, detour, conflicts = plan_route(
        shuttle.shuttle_id,
        task_id,
        side,
        "delivery",
        pick_end,
        platter,
        reader_position,
        reservations + local_segments,
        config,
        coordinated,
    )
    actual_delivery_start = delivery[0].start if delivery else pick_end
    local_segments.extend(
        _pocket_wait(
            shuttle.shuttle_id,
            task_id,
            pick_end,
            actual_delivery_start,
            platter,
        )
    )
    local_segments.extend(delivery)
    delivery_wait_s = wait
    delivery_detour_s = detour
    conflict_wait_s += wait
    detour_s += detour
    conflict_count += conflicts

    reader_ready = max(delivery_end, reader_free[reader_id])
    reader_queue_s = reader_ready - delivery_end
    local_segments.extend(
        _pocket_wait(
            shuttle.shuttle_id,
            task_id,
            delivery_end,
            reader_ready,
            reader_position,
        )
    )
    read_duration = (
        config.reader_load_s
        + config.reader_mount_s
        + work.size_bytes / (1024**2 * config.reader_mib_s)
        + config.reader_unload_s
    )
    service, service_end, wait, conflicts = _hold(
        shuttle.shuttle_id,
        task_id,
        side,
        "reader_service",
        reader_ready,
        read_duration,
        reader_position,
        reservations + local_segments,
        config,
        coordinated,
    )
    local_segments.extend(
        _pocket_wait(
            shuttle.shuttle_id,
            task_id,
            reader_ready,
            service.start,
            reader_position,
        )
    )
    local_segments.append(service)
    reader_conflict_wait_s = wait
    conflict_wait_s += wait
    conflict_count += conflicts
    reader_free[reader_id] = service_end

    returning, return_end, wait, detour, conflicts = plan_route(
        shuttle.shuttle_id,
        task_id,
        side,
        "return",
        service_end,
        reader_position,
        platter,
        reservations + local_segments,
        config,
        coordinated,
    )
    actual_return_start = returning[0].start if returning else service_end
    local_segments.extend(
        _pocket_wait(
            shuttle.shuttle_id,
            task_id,
            service_end,
            actual_return_start,
            reader_position,
        )
    )
    local_segments.extend(returning)
    return_wait_s = wait
    return_detour_s = detour
    conflict_wait_s += wait
    detour_s += detour
    conflict_count += conflicts

    place, end_s, wait, conflicts = _hold(
        shuttle.shuttle_id,
        task_id,
        side,
        "place",
        return_end,
        config.place_s,
        platter,
        reservations + local_segments,
        config,
        coordinated,
    )
    local_segments.extend(
        _pocket_wait(
            shuttle.shuttle_id,
            task_id,
            return_end,
            place.start,
            platter,
        )
    )
    local_segments.append(place)
    place_wait_s = wait
    conflict_wait_s += wait
    conflict_count += conflicts

    fetch_direct_s = _direct_duration(
            shuttle.shuttle_id,
            task_id,
            side,
            "fetch",
            source,
            platter,
            config,
        )
    delivery_direct_s = _direct_duration(
            shuttle.shuttle_id,
            task_id,
            side,
            "delivery",
            platter,
            reader_position,
            config,
        )
    return_direct_s = _direct_duration(
            shuttle.shuttle_id,
            task_id,
            side,
            "return",
            reader_position,
            platter,
            config,
        )
    base_cycle_s = (
        fetch_direct_s
        + config.pick_s
        + delivery_direct_s
        + read_duration
        + return_direct_s
        + config.place_s
    )
    actual_cycle_s = end_s - start_s
    shuttle.position = platter
    shuttle.free_s = end_s
    shuttle.active_s += actual_cycle_s
    shuttle.holding_s += conflict_wait_s + reader_queue_s
    shuttle.detour_s += detour_s
    shuttle.conflict_count += conflict_count
    return (
        ScheduledJob(
            task_id=task_id,
            shuttle_id=shuttle.shuttle_id,
            reader_id=reader_id,
            zone_id=zone_for(position, config),
            start_s=start_s,
            end_s=end_s,
            base_cycle_s=base_cycle_s,
            actual_cycle_s=actual_cycle_s,
            conflict_wait_s=conflict_wait_s,
            detour_s=detour_s,
            conflict_count=conflict_count,
            reader_queue_s=reader_queue_s,
            fetch_direct_s=fetch_direct_s,
            delivery_direct_s=delivery_direct_s,
            return_direct_s=return_direct_s,
            reader_service_s=read_duration,
            pick_place_s=config.pick_s + config.place_s,
            fetch_coordination_s=fetch_wait_s + fetch_detour_s,
            pick_coordination_s=pick_wait_s,
            delivery_coordination_s=delivery_wait_s + delivery_detour_s,
            reader_coordination_s=reader_conflict_wait_s,
            return_coordination_s=return_wait_s + return_detour_s,
            place_coordination_s=place_wait_s,
            size_bytes=work.size_bytes,
            logical_requests=work.logical_request_count,
        ),
        local_segments,
    )


def simulate_policy(
    work: list[VirtualPlatterWork],
    positions: dict[int, tuple[int, float, float]],
    config: ComparisonConfig,
    policy: str,
) -> tuple[dict[str, Any], list[ScheduledJob], list[Segment]]:
    if policy not in {*POLICIES, NO_ZONE_VIRTUAL}:
        raise ValueError(f"Unsupported policy: {policy}")
    readers = reader_positions(config)
    shuttles = [
        ShuttleState(index, reader[0], reader[1:])
        for index, reader in enumerate(readers)
    ]
    reader_free = [0.0] * len(readers)
    pending = sorted(work, key=lambda item: item.first_request_index)
    reservations: list[Segment] = []
    jobs: list[ScheduledJob] = []

    while pending:
        if policy == STATIC_ZONE:
            choices = []
            for shuttle in shuttles:
                queue = [
                    item
                    for item in pending
                    if zone_for(positions[item.virtual_platter_id], config)
                    == shuttle.shuttle_id
                ]
                if queue:
                    choices.append(
                        (
                            shuttle.free_s,
                            queue[0].first_request_index,
                            shuttle.shuttle_id,
                            queue[0],
                        )
                    )
            if not choices:
                raise RuntimeError("Static policy made no progress")
            _, _, shuttle_id, item = min(choices)
        else:
            earliest_free = min(shuttle.free_s for shuttle in shuttles)
            idle = [
                shuttle
                for shuttle in shuttles
                if shuttle.free_s <= earliest_free + 1e-9
            ]
            compatible = [
                item
                for item in pending
                if any(
                    shuttle.side
                    == positions[item.virtual_platter_id][0]
                    for shuttle in idle
                )
            ]
            if not compatible:
                # The first side to become free may have no pending work.
                feasible_times = [
                    shuttle.free_s
                    for shuttle in shuttles
                    if any(
                        positions[item.virtual_platter_id][0]
                        == shuttle.side
                        for item in pending
                    )
                ]
                earliest_free = min(feasible_times)
                idle = [
                    shuttle
                    for shuttle in shuttles
                    if shuttle.free_s <= earliest_free + 1e-9
                    and any(
                        positions[item.virtual_platter_id][0]
                        == shuttle.side
                        for item in pending
                    )
                ]
                compatible = [
                    item
                    for item in pending
                    if any(
                        shuttle.side
                        == positions[item.virtual_platter_id][0]
                        for shuttle in idle
                    )
                ]
            if policy == NO_ZONE_VIRTUAL:
                candidates = []
                for candidate in idle:
                    for pending_item in compatible:
                        position = positions[pending_item.virtual_platter_id]
                        if candidate.side != position[0]:
                            continue
                        fetch = _direct_duration(
                            candidate.shuttle_id,
                            pending_item.virtual_platter_id,
                            candidate.side,
                            "fetch",
                            candidate.position,
                            position[1:],
                            config,
                        )
                        read_duration = (
                            config.reader_load_s
                            + config.reader_mount_s
                            + pending_item.size_bytes / (1024**2 * config.reader_mib_s)
                            + config.reader_unload_s
                        )
                        reader_completion = min(
                            max(
                                candidate.free_s
                                + fetch
                                + config.pick_s
                                + _direct_duration(
                                    candidate.shuttle_id,
                                    pending_item.virtual_platter_id,
                                    candidate.side,
                                    "delivery",
                                    position[1:],
                                    reader[1:],
                                    config,
                                ),
                                reader_free[index],
                            )
                            + read_duration
                            for index, reader in enumerate(readers)
                            if reader[0] == candidate.side
                        )
                        candidates.append(
                            (
                                reader_completion,
                                fetch,
                                pending_item.first_request_index,
                                pending_item.virtual_platter_id,
                                candidate.shuttle_id,
                                pending_item,
                                candidate,
                            )
                        )
                _, _, _, _, _, item, shuttle = min(candidates)
                position = positions[item.virtual_platter_id]
            else:
                item = min(compatible, key=lambda value: value.first_request_index)
                position = positions[item.virtual_platter_id]
                shuttle = min(
                    (
                        candidate
                        for candidate in idle
                        if candidate.side == position[0]
                    ),
                    key=lambda candidate: (
                        abs(candidate.position[0] - position[1])
                        + abs(candidate.position[1] - position[2]),
                        candidate.shuttle_id,
                    ),
                )
            shuttle_id = shuttle.shuttle_id
        pending.remove(item)
        job, segments = schedule_job(
            item,
            positions[item.virtual_platter_id],
            shuttles[shuttle_id],
            readers,
            reader_free,
            reservations,
            config,
            policy,
        )
        jobs.append(job)
        reservations.extend(
            segment for segment in segments if segment.side >= 0
        )

    makespan_s = max(job.end_s for job in jobs)
    total_active_s = sum(job.actual_cycle_s for job in jobs)
    total_reader_service_s = sum(
        segment.end - segment.start
        for segment in reservations
        if segment.phase == "reader_service"
    )
    total_movement_s = sum(
        segment.end - segment.start
        for segment in reservations
        if segment.phase in {"fetch", "delivery", "return"}
    )
    conflict_wait_s = sum(job.conflict_wait_s for job in jobs)
    detour_s = sum(job.detour_s for job in jobs)
    reader_queue_s = sum(job.reader_queue_s for job in jobs)
    conflict_jobs = sum(job.conflict_count > 0 for job in jobs)
    phase_totals = {
        "fetch_direct_s": sum(job.fetch_direct_s for job in jobs),
        "delivery_direct_s": sum(job.delivery_direct_s for job in jobs),
        "return_direct_s": sum(job.return_direct_s for job in jobs),
        "reader_service_s": sum(job.reader_service_s for job in jobs),
        "pick_place_s": sum(job.pick_place_s for job in jobs),
        "fetch_coordination_s": sum(job.fetch_coordination_s for job in jobs),
        "pick_coordination_s": sum(job.pick_coordination_s for job in jobs),
        "delivery_coordination_s": sum(job.delivery_coordination_s for job in jobs),
        "reader_coordination_s": sum(job.reader_coordination_s for job in jobs),
        "return_coordination_s": sum(job.return_coordination_s for job in jobs),
        "place_coordination_s": sum(job.place_coordination_s for job in jobs),
    }
    zone_completion = {
        zone_id: max(job.end_s for job in jobs if job.zone_id == zone_id)
        for zone_id in range(8)
        if any(job.zone_id == zone_id for job in jobs)
    }
    static_idle_s = max(
        0.0,
        makespan_s * len(shuttles) - total_active_s,
    )
    summary = {
        "policy": policy,
        "physical_tasks": len(jobs),
        "logical_requests": sum(job.logical_requests for job in jobs),
        "unique_bytes": sum(job.size_bytes for job in jobs),
        "makespan_s": makespan_s,
        "logical_throughput_req_s": sum(
            job.logical_requests for job in jobs
        )
        / makespan_s,
        "reader_utilization": total_reader_service_s
        / (makespan_s * len(readers)),
        "shuttle_utilization": total_active_s
        / (makespan_s * len(shuttles)),
        "movement_s": total_movement_s,
        "conflict_wait_s": conflict_wait_s,
        "detour_s": detour_s,
        "reader_queue_s": reader_queue_s,
        "idle_capacity_s": static_idle_s,
        "idle_capacity_share": static_idle_s
        / (makespan_s * len(shuttles)),
        "conflict_affected_tasks": conflict_jobs,
        "conflict_affected_fraction": conflict_jobs / len(jobs),
        "conflict_reservations_encountered": sum(
            job.conflict_count for job in jobs
        ),
        "zone_completion_min_s": min(zone_completion.values()),
        "zone_completion_max_s": max(zone_completion.values()),
        "zone_completion_spread_s": max(zone_completion.values())
        - min(zone_completion.values()),
        **phase_totals,
    }
    if policy == NO_ZONE:
        unresolved = exposure(reservations, config.motion_dict())
        if unresolved:
            raise RuntimeError(
                f"Coordinated schedule retains {len(unresolved)} conflicts"
            )
    if len({job.task_id for job in jobs}) != len(work):
        raise RuntimeError("Physical task service is not one-to-one")
    return summary, jobs, reservations


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aggregates = []
    for length_m in sorted({float(row["length_m"]) for row in rows}):
        for policy in POLICIES:
            group = [
                row
                for row in rows
                if float(row["length_m"]) == length_m
                and row["policy"] == policy
            ]
            aggregate: dict[str, Any] = {
                "length_m": length_m,
                "policy": policy,
                "runs": len(group),
            }
            for metric in group[0]:
                if metric in {"seed", "length_m", "policy"}:
                    continue
                values = [float(row[metric]) for row in group]
                aggregate[f"{metric}_mean"] = mean(values)
                aggregate[f"{metric}_std"] = (
                    pstdev(values) if len(values) > 1 else 0.0
                )
            aggregates.append(aggregate)
    return aggregates


def _paired_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = {
        (int(row["seed"]), float(row["length_m"]), str(row["policy"])): row
        for row in rows
    }
    paired = []
    for seed, length_m in sorted(
        {
            (int(row["seed"]), float(row["length_m"]))
            for row in rows
        }
    ):
        if (seed, length_m, STATIC_ZONE) not in indexed:
            continue
        static = indexed[(seed, length_m, STATIC_ZONE)]
        no_zone = indexed[(seed, length_m, NO_ZONE)]
        paired.append(
            {
                "seed": seed,
                "length_m": length_m,
                "no_zone_speedup": static["makespan_s"]
                / no_zone["makespan_s"],
                "no_zone_throughput_change": no_zone[
                    "logical_throughput_req_s"
                ]
                / static["logical_throughput_req_s"]
                - 1.0,
                "static_idle_capacity_share": static[
                    "idle_capacity_share"
                ],
                "no_zone_coordination_s": no_zone["conflict_wait_s"]
                + no_zone["detour_s"],
                "no_zone_conflict_affected_fraction": no_zone[
                    "conflict_affected_fraction"
                ],
            }
        )
    return paired


def run_comparison(config: ComparisonConfig) -> dict[str, Any]:
    config.validate()
    if _sha256(config.batch_path) != config.batch_sha256:
        raise ValueError("Trace checksum mismatch")
    accesses = _load_batch(config.batch_path)
    rows: list[dict[str, Any]] = []
    audit_jobs: list[dict[str, Any]] = []
    audit_segments: list[dict[str, Any]] = []
    signatures: dict[int, tuple[tuple[int, int, int], ...]] = {}
    for seed in config.seeds:
        work = build_virtual_platter_work(
            accesses,
            config.platter_count,
            seed,
        )
        signatures[seed] = tuple(
            sorted(
                (
                    item.virtual_platter_id,
                    item.size_bytes,
                    item.logical_request_count,
                )
                for item in work
            )
        )
        for length_m in config.lengths_m:
            positions = physical_positions(work, config, seed, length_m)
            policy_results = {}
            for policy in POLICIES:
                summary, jobs, segments = simulate_policy(
                    work,
                    positions,
                    config,
                    policy,
                )
                if summary["physical_tasks"] != config.platter_count:
                    raise RuntimeError("Physical work changed")
                if summary["logical_requests"] != len(accesses):
                    raise RuntimeError("Logical work changed")
                row = {
                    "seed": seed,
                    "length_m": length_m,
                    **summary,
                }
                rows.append(row)
                policy_results[policy] = row
                if (
                    seed == config.seeds[0]
                    and length_m == config.lengths_m[-1]
                ):
                    audit_jobs.extend(
                        {
                            "policy": policy,
                            **asdict(job),
                        }
                        for job in jobs
                    )
                    audit_segments.extend(
                        {
                            "policy": policy,
                            **asdict(segment),
                        }
                        for segment in segments
                    )
            if policy_results[STATIC_ZONE]["unique_bytes"] != policy_results[
                NO_ZONE
            ]["unique_bytes"]:
                raise RuntimeError("Policy byte totals differ")
    aggregate = _aggregate(rows)
    paired = _paired_rows(rows)
    result = {
        "config": config.to_json_dict(),
        "source": {
            "dataset": "Azure Functions Blob Access Trace 2020",
            "logical_requests": len(accesses),
            "logical_bytes": sum(access.size_bytes for access in accesses),
            "arrival_span_s": max(
                0,
                _arrival_span(config.batch_path),
            ),
        },
        "runs": rows,
        "aggregate": aggregate,
        "paired": paired,
        "validation": {
            "passed": True,
            "same_trace": True,
            "same_merged_work_per_seed": True,
            "same_positions_across_policies": True,
            "fixed_resources": {"readers": 8, "shuttles": 8},
            "static_conflicts": "zero by construction",
            "no_zone_unresolved_conflicts": 0,
            "work_signatures_recorded": len(signatures),
        },
    }
    output = config.output_dir
    output.mkdir(parents=True, exist_ok=True)
    _write_csv(output / "runs.csv", rows)
    _write_csv(output / "aggregate.csv", aggregate)
    _write_csv(output / "paired.csv", paired)
    _write_csv(output / "audit_jobs.csv", audit_jobs)
    _write_csv(output / "audit_segments.csv", audit_segments)
    (output / "summary.json").write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_report(output / "ANALYSIS_ZH.md", result)
    _plot_results(result, output)
    return result


def _arrival_span(path: Path) -> float:
    import gzip

    first = None
    last = None
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            arrival = int(row["ArrivalMs"])
            first = arrival if first is None else first
            last = arrival
    return ((last or 0) - (first or 0)) / 1000.0


def _policy_rows(
    aggregate: list[dict[str, Any]],
    policy: str,
) -> list[dict[str, Any]]:
    return sorted(
        [row for row in aggregate if row["policy"] == policy],
        key=lambda row: float(row["length_m"]),
    )


def _write_report(path: Path, result: dict[str, Any]) -> None:
    aggregate = result["aggregate"]
    static = _policy_rows(aggregate, STATIC_ZONE)
    no_zone = _policy_rows(aggregate, NO_ZONE)
    lines = [
        "# Static Zone vs. Coordinated No-Zone",
        "",
        "## 這個實驗回答什麼",
        "",
        "用相同 Azure head-100k trace-derived closed batch、相同 platter packing/placement、8 readers 與 8 shuttles，比較 strict static ownership 與可跨 zone 的 nearest-idle dispatch。",
        "",
        "## 主要差異",
        "",
        "- Static Zone：每片 platter 只能由其 level-band owner 處理，每個 owner 使用固定 reader；不同 zones 的 conflict 設為零。",
        "- No-Zone Coordinated：同側 panel 最近的空閒 shuttle 接手，使用最近 reader；route 若與已預約的 shuttle path/operation 衝突，controller 比較 direct 與 alternate-level candidates，選最早安全完成者。",
        "- 等待發生在抽象 holding pocket；這是 controller admission model，不代表 prototype 已有相同硬體 buffer。",
        "",
        "## 結果",
        "",
        "| Side 長度 | Static completion | No-zone completion | No-zone throughput change | Static idle share | No-zone coordination |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    paired_by_length = {}
    for length in result["config"]["lengths_m"]:
        group = [row for row in result["paired"] if row["length_m"] == length]
        paired_by_length[length] = group
    for static_row, no_zone_row in zip(static, no_zone):
        length = static_row["length_m"]
        group = paired_by_length[length]
        change = mean(row["no_zone_throughput_change"] for row in group)
        lines.append(
            f"| {length:g} m | {static_row['makespan_s_mean']/60:.2f} min | "
            f"{no_zone_row['makespan_s_mean']/60:.2f} min | {change:+.1%} | "
            f"{static_row['idle_capacity_share_mean']:.1%} | "
            f"{no_zone_row['conflict_wait_s_mean'] + no_zone_row['detour_s_mean']:.1f} shuttle-s |"
        )
    lines.extend(
        [
            "",
            "## Observation 1：一次 Glass Service 花在哪裡",
            "",
            f"圖三使用兩邊完全相同的 {result['config']['platter_count']} 個 batch-merged tasks，分解 fetch、delivery、return、reader、pick/place 與 conflict avoidance。No-zone 除了 coordination，fetch direct movement 也更長；目前 global FIFO + nearest-idle dispatch 會讓 shuttle 離開原本的 spatial locality。這是此 baseline 的行為，不是所有 MAPF 必然如此。",
            "",
            "## Observation 2：兩種 Tail 代價",
            "",
            f"Static 在所有測試長度都約有 {mean(row['idle_capacity_share_mean'] for row in static):.0%} shuttle capacity 在等待最慢 zone drain；最快與最慢 zone 的絕對 completion gap 則由約 {static[0]['zone_completion_spread_s_mean']/60:.1f} 分鐘增加到 {static[-1]['zone_completion_spread_s_mean']/60:.1f} 分鐘。No-zone 將 idle share 降至約 {mean(row['idle_capacity_share_mean'] for row in no_zone):.0%}，但 {min(row['conflict_affected_fraction_mean'] for row in no_zone):.0%}--{max(row['conflict_affected_fraction_mean'] for row in no_zone):.0%} tasks 需要 coordination，還同時付出跨 level fetch、reader queue、holding 與 detour。",
            "",
            "因此目前觀察不是單純 idle time 對 conflict time：Static 以固定 ownership 換得 collision isolation 和 locality；No-zone 以共享 work pool 降低 stranded capacity，卻失去 locality並承擔 coordination。圖四把兩種代價並列，圖五再顯示 conflict cost 出現在哪個 service phase。",
            "",
            "## Evidence boundary",
            "",
            "- Azure trace 保留 object identity、bytes、reuse 與自然順序，但實驗在 batch barrier 後一次排程；原始 4.15 h interarrival 沒有重播。",
            "- Azure 沒有 glass locations；object-to-platter 與 platter-to-position 都是 seeded mapping。Seeds 是 placement sensitivity，不是獨立 workload samples。",
            "- Static zero-conflict 是 strict non-overlap abstraction；不代表真實 Silica boundary 永遠零 conflict。",
            "- No-zone waiting 使用抽象 holding pockets；idle parked shuttle 不占 rail。這可能低估真實 traffic cost。",
            "- Route candidates 是 horizontal-first 或經單一 intermediate level；不是完整 MAPF，也沒有 controller CPU time。",
            "- 這是第一版 policy comparison。結論只能套用到目前 geometry、mapping、batch semantics 與 routing rules。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _plot_results(result: dict[str, Any], output: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/glint-mplconfig")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    aggregate = result["aggregate"]
    static = _policy_rows(aggregate, STATIC_ZONE)
    no_zone = _policy_rows(aggregate, NO_ZONE)
    labels = [f"{row['length_m']:g}" for row in static]
    x = list(range(len(labels)))
    width = 0.34

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.3))
    axes[0].bar(
        [value - width / 2 for value in x],
        [row["makespan_s_mean"] / 60 for row in static],
        width,
        yerr=[row["makespan_s_std"] / 60 for row in static],
        capsize=3,
        color="#6f7b83",
        label="Static zone",
    )
    axes[0].bar(
        [value + width / 2 for value in x],
        [row["makespan_s_mean"] / 60 for row in no_zone],
        width,
        yerr=[row["makespan_s_std"] / 60 for row in no_zone],
        capsize=3,
        color="#327ba4",
        label="No-zone coordinated",
    )
    axes[0].set_ylabel("Batch completion (min)")
    axes[0].set_title("(a) End-to-end performance", loc="left", fontsize=11)
    axes[0].legend(frameon=False, fontsize=9)

    changes = []
    errors = []
    for length in result["config"]["lengths_m"]:
        values = [
            row["no_zone_throughput_change"] * 100
            for row in result["paired"]
            if row["length_m"] == length
        ]
        changes.append(mean(values))
        errors.append(pstdev(values))
    colors = ["#569769" if value >= 0 else "#c35c55" for value in changes]
    axes[1].bar(x, changes, yerr=errors, capsize=3, color=colors)
    axes[1].axhline(0, color="#59636a", linewidth=1)
    axes[1].set_ylabel("No-zone throughput change vs. static (%)")
    axes[1].set_title("(b) Which policy wins?", loc="left", fontsize=11)
    for axis in axes:
        axis.set_xticks(x, labels)
        axis.set_xlabel("Panel-side length (m)")
        axis.spines[["top", "right"]].set_visible(False)
        axis.grid(axis="y", alpha=0.2)
        axis.set_axisbelow(True)
    fig.text(
        0.5,
        0.02,
        "Azure head-100k trace-derived closed batch; paired synthetic placement. Error bars: seed SD.",
        ha="center",
        fontsize=8,
    )
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    for extension in ("png", "pdf"):
        fig.savefig(output / f"fig1_policy_performance.{extension}", dpi=200)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.3))
    axes[0].bar(
        x,
        [row["idle_capacity_share_mean"] * 100 for row in static],
        color="#6f7b83",
        yerr=[row["idle_capacity_share_std"] * 100 for row in static],
        capsize=3,
    )
    axes[0].set_ylabel("Static idle shuttle-capacity (%)")
    axes[0].set_title("(a) Cost of fixed ownership", loc="left", fontsize=11)

    waits = [row["conflict_wait_s_mean"] for row in no_zone]
    detours = [row["detour_s_mean"] for row in no_zone]
    axes[1].bar(x, waits, color="#d29c39", label="Conflict holding")
    axes[1].bar(
        x,
        detours,
        bottom=waits,
        color="#569769",
        label="Extra detour travel",
    )
    axes[1].set_ylabel("Accumulated coordination cost (shuttle-s)")
    axes[1].set_title("(b) Cost of shared movement", loc="left", fontsize=11)
    axes[1].legend(frameon=False, fontsize=9)
    for axis in axes:
        axis.set_xticks(x, labels)
        axis.set_xlabel("Panel-side length (m)")
        axis.spines[["top", "right"]].set_visible(False)
        axis.grid(axis="y", alpha=0.2)
        axis.set_axisbelow(True)
    fig.text(
        0.5,
        0.02,
        "Different denominators: static idle is capacity share; no-zone coordination is cumulative shuttle time.",
        ha="center",
        fontsize=8,
    )
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    for extension in ("png", "pdf"):
        fig.savefig(output / f"fig2_why_policies_differ.{extension}", dpi=200)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 4.6))
    components = [
        ("fetch_direct_s", "Fetch movement", "#327ba4"),
        ("delivery_direct_s", "Move to reader", "#65a4bf"),
        ("return_direct_s", "Return movement", "#9bc3d2"),
        ("pick_place_s", "Pick/place", "#b5bdc5"),
        ("reader_queue_s", "Reader queue", "#ae6d91"),
        ("reader_service_s", "Reader service", "#808790"),
    ]
    ordered = [row for pair in zip(static, no_zone) for row in pair]
    for index, row in enumerate(ordered):
        bottom = 0.0
        tasks = row["physical_tasks_mean"]
        for metric, label, color in components:
            value = row[f"{metric}_mean"] / tasks
            ax.bar(index, value, bottom=bottom, color=color,
                   label=label if index == 0 else None)
            bottom += value
        coordination = (
            row["conflict_wait_s_mean"] + row["detour_s_mean"]
        ) / tasks
        ax.bar(index, coordination, bottom=bottom, color="#daa24b",
               label="Conflict avoidance" if index == 0 else None)
    ax.set_xticks(
        range(len(ordered)),
        [f"{row['length_m']:g}m\n{'Zone' if row['policy']==STATIC_ZONE else 'No-zone'}" for row in ordered],
    )
    ax.set_ylabel("Average time per physical service (s)")
    ax.set_title("Observation 1: One glass service, stage by stage", loc="left", fontsize=12)
    ax.legend(ncol=4, frameon=False, fontsize=8.5, loc="upper left")
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(.5,.018,f"Same {result['config']['platter_count']} batch-merged platter tasks under both policies; request arrivals are held behind a batch barrier.",ha="center",fontsize=8)
    fig.tight_layout(rect=(0,.065,1,1))
    for extension in ("png", "pdf"):
        fig.savefig(output / f"fig3_service_phase_breakdown.{extension}", dpi=200)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.3))
    idle = [row["idle_capacity_share_mean"] * 100 for row in static]
    axes[0].bar(x, idle, width=.48, color="#6f7b83")
    axes[0].set_ylim(0, max(idle) * 1.24)
    for xpos, value, row in zip(x, idle, static):
        spread = row["zone_completion_spread_s_mean"] / 60
        axes[0].text(xpos, value + 1.5, f"{spread:.1f} min\ndrain gap", ha="center", fontsize=9)
    axes[0].set_ylabel("Idle shuttle capacity before batch drain (%)")
    axes[0].set_title("(a) Static: slowest-zone cost", loc="left", fontsize=11)

    locality = [
        max(0.0, n["fetch_direct_s_mean"] - s["fetch_direct_s_mean"])
        / n["physical_tasks_mean"]
        for s, n in zip(static, no_zone)
    ]
    waits = [row["conflict_wait_s_mean"] / row["physical_tasks_mean"] for row in no_zone]
    detours = [row["detour_s_mean"] / row["physical_tasks_mean"] for row in no_zone]
    reader_queues = [row["reader_queue_s_mean"] / row["physical_tasks_mean"] for row in no_zone]
    axes[1].bar(x, locality, width=.48, color="#327ba4", label="Lost fetch locality")
    axes[1].bar(x, waits, width=.48, bottom=locality, color="#daa24b", label="Holding")
    first_bottom = [a+b for a,b in zip(locality,waits)]
    axes[1].bar(x, detours, width=.48, bottom=first_bottom, color="#6c9e69", label="Detour")
    second_bottom = [a+b for a,b in zip(first_bottom,detours)]
    axes[1].bar(x, reader_queues, width=.48, bottom=second_bottom, color="#ae6d91", label="Reader queue")
    totals = [a+b for a,b in zip(second_bottom,reader_queues)]
    axes[1].set_ylim(0, max(totals) * 1.25)
    for xpos, total, row in zip(x, totals, no_zone):
        axes[1].text(xpos, total + .3, f"{row['conflict_affected_fraction_mean']:.0%} affected", ha="center", fontsize=9)
    axes[1].set_ylabel("Extra time per physical service (s)")
    axes[1].set_title("(b) No-zone: shared-mobility cost", loc="left", fontsize=11)
    axes[1].legend(frameon=False, fontsize=8.5, loc="upper left", bbox_to_anchor=(1.01, 1))
    for axis in axes:
        axis.set_xticks(x, labels)
        axis.set_xlabel("Panel-side length (m)")
        axis.spines[["top", "right"]].set_visible(False)
    fig.text(.5,.018,"Static pays in stranded capacity; no-zone pays in lost locality, conflict avoidance, and shared-reader waiting.",ha="center",fontsize=8)
    fig.tight_layout(rect=(0,.065,1,1))
    for extension in ("png", "pdf"):
        fig.savefig(output / f"fig4_isolation_vs_coordination.{extension}", dpi=200)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    phase_components = [
        ("rack", "Rack access", "#327ba4"),
        ("delivery", "Move to reader", "#6c9e69"),
        ("reader", "Reader area", "#ae6d91"),
        ("return", "Return/place", "#daa24b"),
    ]
    bottoms = [0.0] * len(no_zone)
    for key, label, color in phase_components:
        if key == "rack":
            values = [(r["fetch_coordination_s_mean"] + r["pick_coordination_s_mean"]) / r["physical_tasks_mean"] for r in no_zone]
        elif key == "delivery":
            values = [r["delivery_coordination_s_mean"] / r["physical_tasks_mean"] for r in no_zone]
        elif key == "reader":
            values = [r["reader_coordination_s_mean"] / r["physical_tasks_mean"] for r in no_zone]
        else:
            values = [(r["return_coordination_s_mean"] + r["place_coordination_s_mean"]) / r["physical_tasks_mean"] for r in no_zone]
        ax.bar(x, values, bottom=bottoms, width=.48, color=color, label=label)
        bottoms = [a+b for a,b in zip(bottoms,values)]
    ax.set_xticks(x, labels)
    ax.set_xlabel("Panel-side length (m)")
    ax.set_ylabel("Coordination time per physical service (s)")
    ax.set_title("Observation 2: Where no-zone coordination appears", loc="left", fontsize=11)
    ax.legend(frameon=False, fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    for extension in ("png", "pdf"):
        fig.savefig(output / f"fig5_nozone_coordination_location.{extension}", dpi=200)
    plt.close(fig)
