from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import csv
import json
from pathlib import Path
from statistics import mean
from typing import Iterable

from .config import ArchitectureConfig, SimulationConfig, TimingConfig
from .trace import TraceRequest


@dataclass(frozen=True)
class Placement:
    platter_id: int
    row: int
    column: int
    zone: int


@dataclass(frozen=True)
class RequestResult:
    request_index: int
    arrival_s: float
    io_type: str
    lun: int
    offset: int
    size_bytes: int
    platter_id: int
    row: int
    column: int
    zone: int
    cache_hit: bool
    fetch_start_s: float
    fetch_done_s: float
    reader_id: int
    read_start_s: float
    read_done_s: float
    latency_s: float
    queue_wait_s: float
    fetch_s: float
    read_s: float


@dataclass(frozen=True)
class SimulationResult:
    details: list[RequestResult]
    summary: dict[str, object]


class GlassV2Simulator:
    def __init__(self, config: SimulationConfig) -> None:
        self.config = config
        self.arch = config.architecture
        self.timing = config.timing
        self.zone_count = self.arch.rows // self.arch.rows_per_zone
        self.zone_available_s = [0.0 for _ in range(self.zone_count)]
        self.reader_available_s = [0.0 for _ in range(self.arch.reader_count)]
        self.feeder_buffer: OrderedDict[int, Placement] = OrderedDict()
        self.zone_busy_s = [0.0 for _ in range(self.zone_count)]
        self.reader_busy_s = [0.0 for _ in range(self.arch.reader_count)]

    def run(self, requests: Iterable[TraceRequest]) -> SimulationResult:
        details = [self._serve(request) for request in requests]
        return SimulationResult(details=details, summary=self._build_summary(details))

    def write_outputs(self, result: SimulationResult) -> None:
        output_dir = self.config.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_detail_csv(output_dir / "request_detail.csv", result.details)
        with (output_dir / "summary.json").open("w", encoding="utf-8") as handle:
            json.dump(result.summary, handle, indent=2)
            handle.write("\n")

    def _serve(self, request: TraceRequest) -> RequestResult:
        placement = self._place(request.offset)
        cache_hit = placement.platter_id in self.feeder_buffer
        fetch_start_s = request.arrival_s
        fetch_done_s = request.arrival_s
        fetch_s = 0.0

        if cache_hit:
            self.feeder_buffer.move_to_end(placement.platter_id)
        else:
            fetch_start_s = max(request.arrival_s, self.zone_available_s[placement.zone])
            fetch_s = self._fetch_time_s(placement)
            fetch_done_s = fetch_start_s + fetch_s
            self.zone_available_s[placement.zone] = fetch_done_s
            self.zone_busy_s[placement.zone] += fetch_s
            self._insert_into_buffer(placement, available_after_s=fetch_done_s)

        reader_id = min(range(self.arch.reader_count), key=self.reader_available_s.__getitem__)
        read_start_s = max(fetch_done_s, self.reader_available_s[reader_id])
        read_s = self._read_time_s(request.size_bytes)
        read_done_s = read_start_s + read_s
        self.reader_available_s[reader_id] = read_done_s
        self.reader_busy_s[reader_id] += read_s

        return RequestResult(
            request_index=request.index,
            arrival_s=request.arrival_s,
            io_type=request.io_type,
            lun=request.lun,
            offset=request.offset,
            size_bytes=request.size_bytes,
            platter_id=placement.platter_id,
            row=placement.row,
            column=placement.column,
            zone=placement.zone,
            cache_hit=cache_hit,
            fetch_start_s=fetch_start_s,
            fetch_done_s=fetch_done_s,
            reader_id=reader_id,
            read_start_s=read_start_s,
            read_done_s=read_done_s,
            latency_s=read_done_s - request.arrival_s,
            queue_wait_s=max(0.0, read_start_s - request.arrival_s - fetch_s),
            fetch_s=fetch_s,
            read_s=read_s,
        )

    def _insert_into_buffer(self, placement: Placement, available_after_s: float) -> None:
        if self.arch.feeder_buffer_slots == 0:
            self._schedule_return(placement, available_after_s)
            return

        self.feeder_buffer[placement.platter_id] = placement
        self.feeder_buffer.move_to_end(placement.platter_id)
        while len(self.feeder_buffer) > self.arch.feeder_buffer_slots:
            _, evicted = self.feeder_buffer.popitem(last=False)
            self._schedule_return(evicted, available_after_s)

    def _schedule_return(self, placement: Placement, available_after_s: float) -> None:
        start_s = max(available_after_s, self.zone_available_s[placement.zone])
        return_s = self._return_time_s(placement)
        self.zone_available_s[placement.zone] = start_s + return_s
        self.zone_busy_s[placement.zone] += return_s

    def _place(self, offset: int) -> Placement:
        platter_id = offset // self.arch.glass_capacity_bytes
        slot = platter_id % (self.arch.rows * self.arch.columns)
        row = slot // self.arch.columns
        column = slot % self.arch.columns
        zone = row // self.arch.rows_per_zone
        return Placement(platter_id=platter_id, row=row, column=column, zone=zone)

    def _fetch_time_s(self, placement: Placement) -> float:
        distance_to_feeder = self.arch.columns - 1 - placement.column
        return (
            self.timing.zone_pick_s
            + self.timing.zone_place_s
            + distance_to_feeder * self.timing.horizontal_slot_s
        )

    def _return_time_s(self, placement: Placement) -> float:
        distance_from_feeder = self.arch.columns - 1 - placement.column
        return (
            self.timing.return_pick_s
            + self.timing.return_place_s
            + distance_from_feeder * self.timing.horizontal_slot_s
        )

    def _read_time_s(self, size_bytes: int) -> float:
        mib = size_bytes / (1024 * 1024)
        return self.timing.reader_fixed_s + mib / self.timing.reader_mib_per_s

    def _build_summary(self, details: list[RequestResult]) -> dict[str, object]:
        latencies = [row.latency_s for row in details]
        fetch_times = [row.fetch_s for row in details]
        read_times = [row.read_s for row in details]
        cache_hits = sum(1 for row in details if row.cache_hit)
        arrival_span_s = details[-1].arrival_s - details[0].arrival_s if len(details) > 1 else 0.0
        finish_s = max((row.read_done_s for row in details), default=0.0)
        makespan_s = max(finish_s - (details[0].arrival_s if details else 0.0), 0.0)

        return {
            "config": self.config.to_json_dict(),
            "request_count": len(details),
            "arrival_span_s": arrival_span_s,
            "finish_s": finish_s,
            "makespan_s": makespan_s,
            "throughput_req_per_s": len(details) / makespan_s if makespan_s > 0 else 0.0,
            "latency_s": _stats(latencies),
            "fetch_s": _stats(fetch_times),
            "read_s": _stats(read_times),
            "cache_hits": cache_hits,
            "cache_hit_rate": cache_hits / len(details) if details else 0.0,
            "zone_utilization": _utilization(self.zone_busy_s, finish_s),
            "reader_utilization": _utilization(self.reader_busy_s, finish_s),
            "assumptions": [
                "Offsets map to platters by floor(offset / glass_capacity_bytes).",
                "Rows are partitioned into equal logical zones.",
                "A feeder-buffer hit skips zone-shuttle fetch time.",
                "Evicted feeder-buffer entries schedule return work on the owning zone shuttle.",
                "Reader service time is fixed_s + size / throughput.",
            ],
        }


def _write_detail_csv(path: Path, details: list[RequestResult]) -> None:
    fieldnames = list(RequestResult.__dataclass_fields__.keys())
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


def _percentile(ordered: list[float], quantile: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    position = quantile * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _utilization(busy_times: list[float], finish_s: float) -> list[dict[str, float]]:
    if finish_s <= 0:
        return [{"id": index, "busy_s": busy, "utilization": 0.0} for index, busy in enumerate(busy_times)]
    return [
        {"id": index, "busy_s": busy, "utilization": min(busy / finish_s, 1.0)}
        for index, busy in enumerate(busy_times)
    ]
