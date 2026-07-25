from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import csv
from itertools import combinations
import json
import math
import os
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Iterable

from .panel_static_zone import (
    MIB,
    PanelGeometryConfig,
    PanelMovementConfig,
    PanelRequest,
    PanelStaticZoneConfig,
    PanelStaticZoneResult,
    PanelStaticZoneSimulator,
    PanelTimingConfig,
    PanelWorkloadConfig,
    ZoneState,
    merge_panel_requests,
)
from .paths import portable_path, repository_root_for_config
from .static_baseline_study import generate_paired_requests


SIDES = ("left", "right")


@dataclass(frozen=True)
class AdaptiveZoneWorkloadConfig:
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
class AdaptiveZoneStudyConfig:
    output_dir: Path
    seeds: tuple[int, ...]
    hot_zone_fractions: tuple[float, ...]
    geometry: PanelGeometryConfig
    movement: PanelMovementConfig
    timing: PanelTimingConfig
    workload: AdaptiveZoneWorkloadConfig

    @property
    def zones_per_side(self) -> int:
        return self.geometry.levels // self.geometry.zone_height_racks

    @property
    def zone_count(self) -> int:
        return self.zones_per_side * 2

    @property
    def balanced_fraction(self) -> float:
        return 1.0 / self.zone_count

    def validate(self) -> None:
        self.geometry.validate()
        self.movement.validate()
        self.timing.validate()
        self.workload.validate()
        if not self.seeds:
            raise ValueError("seeds cannot be empty")
        if self.zones_per_side <= 0 or self.zones_per_side > self.geometry.levels:
            raise ValueError("the geometry must permit positive-height zones on each side")
        if self.workload.hot_zone >= self.zone_count:
            raise ValueError("workload.hot_zone must be within the panel zone count")
        if any(
            fraction < self.balanced_fraction or fraction > 1.0
            for fraction in self.hot_zone_fractions
        ):
            raise ValueError("hot_zone_fractions must be between balanced share and 1")
        if not any(
            math.isclose(fraction, self.balanced_fraction)
            for fraction in self.hot_zone_fractions
        ):
            raise ValueError("hot_zone_fractions must include the balanced zone share")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "output_dir": portable_path(self.output_dir),
            "seeds": list(self.seeds),
            "hot_zone_fractions": list(self.hot_zone_fractions),
            "request_merge": True,
            "adaptive_upper_bound": True,
            "reconfiguration_cost": False,
            "geometry": asdict(self.geometry),
            "movement": asdict(self.movement),
            "timing": asdict(self.timing),
            "workload": asdict(self.workload),
        }


@dataclass(frozen=True)
class ZoneRegion:
    zone_id: int
    ordinal: int
    side: str
    start_level: int
    end_level: int
    reader_level: int
    reader_slot_in_half: int

    @property
    def height(self) -> int:
        return self.end_level - self.start_level

    def contains(self, request: PanelRequest) -> bool:
        return request.side == self.side and self.start_level <= request.level < self.end_level


@dataclass(frozen=True)
class LayoutScore:
    max_estimated_work_s: float
    absolute_deviation_s: float
    boundary_displacement_levels: int

    def objective(self) -> tuple[float, float, int]:
        return (
            self.max_estimated_work_s,
            self.absolute_deviation_s,
            self.boundary_displacement_levels,
        )


@dataclass(frozen=True)
class AdaptiveZoneStudyResult:
    run_rows: list[dict[str, Any]]
    aggregate_rows: list[dict[str, Any]]
    validation: dict[str, Any]
    findings: dict[str, Any]
    representative: dict[str, Any]


def load_adaptive_zone_study_config(path: str | Path) -> AdaptiveZoneStudyConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    base_dir = repository_root_for_config(config_path)
    output_dir = Path(raw["output_dir"]).expanduser()
    if not output_dir.is_absolute():
        output_dir = (base_dir / output_dir).resolve()
    config = AdaptiveZoneStudyConfig(
        output_dir=output_dir,
        seeds=tuple(int(value) for value in raw["seeds"]),
        hot_zone_fractions=tuple(float(value) for value in raw["hot_zone_fractions"]),
        geometry=PanelGeometryConfig(**raw["geometry"]),
        movement=PanelMovementConfig(**raw["movement"]),
        timing=PanelTimingConfig(**raw["timing"]),
        workload=AdaptiveZoneWorkloadConfig(**raw["workload"]),
    )
    config.validate()
    return config


def enumerate_zone_heights(levels: int, zones_per_side: int) -> list[tuple[int, ...]]:
    if zones_per_side <= 0 or zones_per_side > levels:
        raise ValueError("zones_per_side must be between 1 and levels")
    layouts = []
    for cuts in combinations(range(1, levels), zones_per_side - 1):
        boundaries = (0, *cuts, levels)
        layouts.append(
            tuple(boundaries[index + 1] - boundaries[index] for index in range(zones_per_side))
        )
    return layouts


def build_layout(
    geometry: PanelGeometryConfig,
    left_heights: tuple[int, ...],
    right_heights: tuple[int, ...],
) -> tuple[ZoneRegion, ...]:
    if sum(left_heights) != geometry.levels or sum(right_heights) != geometry.levels:
        raise ValueError("zone heights on each side must cover all panel levels")
    if len(left_heights) != len(right_heights) or any(
        height <= 0 for height in (*left_heights, *right_heights)
    ):
        raise ValueError("both sides require the same number of positive-height zones")

    by_id: list[ZoneRegion | None] = [None] * (len(left_heights) * 2)
    for side_index, (side, heights) in enumerate(
        (("left", left_heights), ("right", right_heights))
    ):
        start = 0
        reader_slot = 0 if side == "left" else geometry.slots_per_half - 1
        for ordinal, height in enumerate(heights):
            end = start + height
            zone_id = ordinal * 2 + side_index
            by_id[zone_id] = ZoneRegion(
                zone_id=zone_id,
                ordinal=ordinal,
                side=side,
                start_level=start,
                end_level=end,
                reader_level=start + height // 2,
                reader_slot_in_half=reader_slot,
            )
            start = end
    layout = tuple(region for region in by_id if region is not None)
    validate_layout(layout, geometry.levels, len(left_heights))
    return layout


def static_layout(geometry: PanelGeometryConfig) -> tuple[ZoneRegion, ...]:
    heights = (geometry.zone_height_racks,) * (
        geometry.levels // geometry.zone_height_racks
    )
    return build_layout(geometry, heights, heights)


def validate_layout(
    layout: Iterable[ZoneRegion],
    levels: int,
    zones_per_side: int,
) -> None:
    regions = tuple(layout)
    if len(regions) != zones_per_side * 2:
        raise ValueError("layout must contain the configured number of zones")
    if sorted(region.zone_id for region in regions) != list(range(len(regions))):
        raise ValueError("layout zone IDs must be contiguous")
    for side in SIDES:
        side_regions = sorted(
            (region for region in regions if region.side == side),
            key=lambda region: region.start_level,
        )
        if len(side_regions) != zones_per_side:
            raise ValueError(f"{side} must contain exactly {zones_per_side} zones")
        cursor = 0
        for region in side_regions:
            if region.start_level != cursor or region.end_level <= region.start_level:
                raise ValueError(f"{side} zones must be contiguous and positive-height")
            if not region.start_level <= region.reader_level < region.end_level:
                raise ValueError("each reader must be inside its zone")
            cursor = region.end_level
        if cursor != levels:
            raise ValueError(f"{side} zones must cover all levels")


class PanelAdaptiveZoneSimulator(PanelStaticZoneSimulator):
    def __init__(
        self,
        config: PanelStaticZoneConfig,
        layout: tuple[ZoneRegion, ...],
    ) -> None:
        validate_layout(
            layout,
            config.geometry.levels,
            config.geometry.levels // config.geometry.zone_height_racks,
        )
        self.layout = layout
        self._region_by_id = {region.zone_id: region for region in layout}
        super().__init__(config)

    def _build_zones(self) -> list[ZoneState]:
        return [
            ZoneState(
                zone_id=region.zone_id,
                row_id=region.ordinal,
                side=region.side,
                reader_level=region.reader_level,
                reader_slot_in_half=region.reader_slot_in_half,
                shuttle_level=region.reader_level,
                shuttle_slot_in_half=region.reader_slot_in_half,
            )
            for region in self.layout
        ]

    def remap_requests(self, requests: list[PanelRequest]) -> list[PanelRequest]:
        remapped = []
        for request in requests:
            region = next(region for region in self.layout if region.contains(request))
            remapped.append(
                replace(
                    request,
                    zone_id=region.zone_id,
                    row_id=region.ordinal,
                    reader_level=region.reader_level,
                    reader_slot_in_half=region.reader_slot_in_half,
                )
            )
        return remapped

    def _build_summary(self, details: list[Any]) -> dict[str, Any]:
        summary = super()._build_summary(details)
        summary["layout"] = "adaptive_contiguous_vertical_regions_x_2_sides"
        summary["adaptive_upper_bound"] = True
        summary["assumptions"] = [
            *summary["assumptions"],
            "Zone boundaries are selected after observing the complete merged batch.",
            "Each adaptive zone selects one region-local reader from a fully populated read rack.",
            "Boundary reconfiguration cost is excluded.",
        ]
        return summary

    def _build_zone_rows(self) -> list[dict[str, Any]]:
        rows = super()._build_zone_rows()
        return [
            {
                **row,
                "start_level": self._region_by_id[int(row["zone_id"])].start_level,
                "end_level": self._region_by_id[int(row["zone_id"])].end_level,
                "height_levels": self._region_by_id[int(row["zone_id"])].height,
            }
            for row in rows
        ]


def optimize_layout(
    config: AdaptiveZoneStudyConfig,
    requests: list[PanelRequest],
) -> tuple[tuple[ZoneRegion, ...], LayoutScore, LayoutScore]:
    panel_config = _panel_config(config, config.balanced_fraction, config.seeds[0])
    estimator = PanelStaticZoneSimulator(panel_config)
    height_options = enumerate_zone_heights(config.geometry.levels, config.zones_per_side)
    side_options: dict[str, list[tuple[tuple[int, ...], tuple[float, ...]]]] = {
        side: [] for side in SIDES
    }
    for side in SIDES:
        side_requests = [request for request in requests if request.side == side]
        for heights in height_options:
            layout = build_layout(
                config.geometry,
                heights if side == "left" else (config.geometry.zone_height_racks,) * config.zones_per_side,
                heights if side == "right" else (config.geometry.zone_height_racks,) * config.zones_per_side,
            )
            loads = tuple(
                sum(
                    _estimate_request_cycle_s(estimator, request, region)
                    for request in side_requests
                    if region.contains(request)
                )
                for region in layout
                if region.side == side
            )
            side_options[side].append((heights, loads))

    best_layout: tuple[ZoneRegion, ...] | None = None
    best_score: LayoutScore | None = None
    for left_heights, left_loads in side_options["left"]:
        for right_heights, right_loads in side_options["right"]:
            loads = (*left_loads, *right_loads)
            average = sum(loads) / len(loads)
            score = LayoutScore(
                max_estimated_work_s=max(loads, default=0.0),
                absolute_deviation_s=sum(abs(load - average) for load in loads),
                boundary_displacement_levels=(
                    _boundary_displacement(left_heights, config.geometry.zone_height_racks)
                    + _boundary_displacement(right_heights, config.geometry.zone_height_racks)
                ),
            )
            if best_score is None or score.objective() < best_score.objective():
                best_score = score
                best_layout = build_layout(config.geometry, left_heights, right_heights)

    if best_layout is None or best_score is None:
        raise RuntimeError("no legal adaptive layout was found")
    baseline = static_layout(config.geometry)
    static_score = score_layout(config, requests, baseline)
    return best_layout, best_score, static_score


def score_layout(
    config: AdaptiveZoneStudyConfig,
    requests: list[PanelRequest],
    layout: tuple[ZoneRegion, ...],
) -> LayoutScore:
    estimator = PanelStaticZoneSimulator(
        _panel_config(config, config.balanced_fraction, config.seeds[0])
    )
    loads = [
        sum(
            _estimate_request_cycle_s(estimator, request, region)
            for request in requests
            if region.contains(request)
        )
        for region in layout
    ]
    average = sum(loads) / len(loads)
    return LayoutScore(
        max_estimated_work_s=max(loads, default=0.0),
        absolute_deviation_s=sum(abs(load - average) for load in loads),
        boundary_displacement_levels=sum(
            _boundary_displacement(
                tuple(region.height for region in layout if region.side == side),
                config.geometry.zone_height_racks,
            )
            for side in SIDES
        ),
    )


def run_adaptive_zone_study(
    config: AdaptiveZoneStudyConfig,
) -> AdaptiveZoneStudyResult:
    config.validate()
    run_rows: list[dict[str, Any]] = []
    failures: list[str] = []
    representative: dict[str, Any] = {}
    maximum_skew = max(config.hot_zone_fractions)

    for hot_fraction in sorted(set(config.hot_zone_fractions)):
        for seed in config.seeds:
            panel_config = _panel_config(config, hot_fraction, seed)
            static_simulator = PanelStaticZoneSimulator(panel_config)
            logical = generate_paired_requests(
                static_simulator,
                batch_size=config.workload.batch_size,
                request_size_bytes=config.workload.request_size_bytes,
                hot_zone=config.workload.hot_zone,
                hot_zone_fraction=hot_fraction,
                hotspot_width=1,
                seed=seed,
            )
            merged = merge_panel_requests(logical)
            layout, adaptive_score, static_score = optimize_layout(config, merged)
            adaptive_simulator = PanelAdaptiveZoneSimulator(panel_config, layout)
            adaptive_requests = adaptive_simulator.remap_requests(merged)
            _validate_paired_trace(
                logical,
                merged,
                adaptive_requests,
                config.workload.batch_size,
                f"hot={hot_fraction:.4f},seed={seed}",
                failures,
            )
            if adaptive_score.objective() > static_score.objective():
                failures.append(
                    f"hot={hot_fraction:.4f},seed={seed}: optimizer is worse than static candidate"
                )

            static_result = static_simulator.run(merged)
            adaptive_result = adaptive_simulator.run(adaptive_requests)
            row = _build_run_row(
                config,
                hot_fraction,
                seed,
                static_result,
                adaptive_result,
                layout,
                adaptive_score,
                static_score,
            )
            run_rows.append(row)
            if math.isclose(hot_fraction, maximum_skew) and seed == config.seeds[0]:
                hot_region = static_layout(config.geometry)[config.workload.hot_zone]
                representative = {
                    "hot_zone_fraction": hot_fraction,
                    "seed": seed,
                    "hot_side": hot_region.side,
                    "hot_start_level": hot_region.start_level,
                    "hot_end_level": hot_region.end_level,
                    "static_layout": _layout_json(static_layout(config.geometry)),
                    "adaptive_layout": _layout_json(layout),
                    "static_zone_rows": static_result.zone_rows,
                    "adaptive_zone_rows": adaptive_result.zone_rows,
                }

    if failures:
        raise RuntimeError("adaptive-zone validation failed: " + "; ".join(failures))
    aggregate_rows = _aggregate(run_rows)
    findings = _findings(config, aggregate_rows)
    validation = {
        "passed": True,
        "checked_runs": len(run_rows),
        "request_merge": True,
        "paired_trace_equivalence": True,
        "eight_shuttles_and_readers": config.zone_count == 8,
        "static_candidate_in_search_space": True,
        "adaptive_objective_not_worse": True,
        "failures": [],
    }
    return AdaptiveZoneStudyResult(
        run_rows=run_rows,
        aggregate_rows=aggregate_rows,
        validation=validation,
        findings=findings,
        representative=representative,
    )


def write_adaptive_zone_outputs(
    config: AdaptiveZoneStudyConfig,
    result: AdaptiveZoneStudyResult,
) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    _write_rows(config.output_dir / "run_summary.csv", result.run_rows)
    _write_rows(config.output_dir / "aggregate_summary.csv", result.aggregate_rows)
    with (config.output_dir / "config.json").open("w", encoding="utf-8") as handle:
        json.dump(config.to_json_dict(), handle, indent=2)
        handle.write("\n")
    with (config.output_dir / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "config": config.to_json_dict(),
                "run_count": len(result.run_rows),
                "aggregate_count": len(result.aggregate_rows),
                "validation": result.validation,
                "findings": result.findings,
                "representative": result.representative,
            },
            handle,
            indent=2,
        )
        handle.write("\n")
    _write_report(
        config.output_dir / "ADAPTIVE_ZONE_UPPER_BOUND_ANALYSIS.md",
        config,
        result,
    )
    figures_dir = config.output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    _write_figures(result, figures_dir)


def _panel_config(
    config: AdaptiveZoneStudyConfig,
    hot_fraction: float,
    seed: int,
) -> PanelStaticZoneConfig:
    return PanelStaticZoneConfig(
        output_dir=config.output_dir,
        seed=seed,
        geometry=config.geometry,
        movement=config.movement,
        timing=config.timing,
        workload=PanelWorkloadConfig(
            batch_size=config.workload.batch_size,
            request_size_bytes=config.workload.request_size_bytes,
            placement="spatial_skew",
            request_merge=True,
            hot_zone=config.workload.hot_zone,
            hot_zone_fraction=hot_fraction,
            hot_zone_width=1,
        ),
    )


def _estimate_request_cycle_s(
    simulator: PanelStaticZoneSimulator,
    request: PanelRequest,
    region: ZoneRegion,
) -> float:
    reader_to_glass = simulator._move_time_s(
        region.reader_level,
        region.reader_slot_in_half,
        request.level,
        request.slot_in_half,
    )
    read_s = simulator._read_time_s(request.size_bytes)
    return (
        reader_to_glass * 3.0
        + simulator.timing.storage_pick_s
        + simulator.timing.reader_load_s
        + read_s
        + simulator.timing.reader_unload_s
        + simulator.timing.storage_place_s
    )


def _boundary_displacement(
    heights: tuple[int, ...],
    static_height: int,
) -> int:
    adaptive_cuts = _cuts(heights)
    static_cuts = tuple(static_height * index for index in range(1, len(heights)))
    return sum(abs(adaptive - static) for adaptive, static in zip(adaptive_cuts, static_cuts))


def _cuts(heights: tuple[int, ...]) -> tuple[int, ...]:
    cuts = []
    cursor = 0
    for height in heights[:-1]:
        cursor += height
        cuts.append(cursor)
    return tuple(cuts)


def _validate_paired_trace(
    logical: list[PanelRequest],
    merged: list[PanelRequest],
    adaptive: list[PanelRequest],
    expected_count: int,
    label: str,
    failures: list[str],
) -> None:
    if len(logical) != expected_count:
        failures.append(f"{label}: logical request count changed")
    if sum(request.merged_request_count for request in merged) != expected_count:
        failures.append(f"{label}: merged logical request count changed")
    if sum(request.size_bytes for request in logical) != sum(
        request.size_bytes for request in merged
    ):
        failures.append(f"{label}: merge changed bytes")
    signature = lambda request: (
        request.request_index,
        request.platter_id,
        request.size_bytes,
        request.merged_request_count,
        request.side,
        request.level,
        request.slot_in_half,
    )
    if [signature(request) for request in merged] != [
        signature(request) for request in adaptive
    ]:
        failures.append(f"{label}: adaptive ownership changed the merged physical trace")


def _build_run_row(
    config: AdaptiveZoneStudyConfig,
    hot_fraction: float,
    seed: int,
    static: PanelStaticZoneResult,
    adaptive: PanelStaticZoneResult,
    layout: tuple[ZoneRegion, ...],
    adaptive_score: LayoutScore,
    static_score: LayoutScore,
) -> dict[str, Any]:
    static_summary = static.summary
    adaptive_summary = adaptive.summary
    static_work = [float(row["active_cycle_s"]) for row in static.zone_rows]
    adaptive_work = [float(row["active_cycle_s"]) for row in adaptive.zone_rows]
    left_heights = tuple(region.height for region in layout if region.side == "left")
    right_heights = tuple(region.height for region in layout if region.side == "right")
    return {
        "seed": seed,
        "hot_zone_fraction_target": hot_fraction,
        "logical_request_count": static_summary["request_count"],
        "service_operation_count": static_summary["service_operation_count"],
        "static_drive_makespan_s": static_summary["drive_makespan_s"],
        "adaptive_drive_makespan_s": adaptive_summary["drive_makespan_s"],
        "static_system_drain_s": static_summary["system_drain_s"],
        "adaptive_system_drain_s": adaptive_summary["system_drain_s"],
        "static_throughput_req_per_s": static_summary["throughput_req_per_s"],
        "adaptive_throughput_req_per_s": adaptive_summary["throughput_req_per_s"],
        "throughput_improvement": (
            adaptive_summary["throughput_req_per_s"]
            / static_summary["throughput_req_per_s"]
        ),
        "drain_speedup": (
            static_summary["system_drain_s"] / adaptive_summary["system_drain_s"]
        ),
        "static_capacity_efficiency": static_summary["static_capacity_efficiency"],
        "adaptive_capacity_efficiency": adaptive_summary["static_capacity_efficiency"],
        "static_stranded_capacity_share": static_summary["stranded_capacity_share"],
        "adaptive_stranded_capacity_share": adaptive_summary["stranded_capacity_share"],
        "static_zone_work_max_mean_ratio": _max_mean_ratio(static_work),
        "adaptive_zone_work_max_mean_ratio": _max_mean_ratio(adaptive_work),
        "static_ideal_lower_bound_s": static_summary["ideal_balanced_cycle_lower_bound_s"],
        "adaptive_ideal_lower_bound_s": adaptive_summary["ideal_balanced_cycle_lower_bound_s"],
        "static_gap_to_ideal": static_summary["ownership_slowdown_vs_ideal"],
        "adaptive_gap_to_ideal": adaptive_summary["ownership_slowdown_vs_ideal"],
        "static_productive_cycle_s": static_summary["productive_cycle_s"],
        "adaptive_productive_cycle_s": adaptive_summary["productive_cycle_s"],
        "adaptive_max_estimated_work_s": adaptive_score.max_estimated_work_s,
        "static_max_estimated_work_s": static_score.max_estimated_work_s,
        "estimated_bottleneck_reduction": (
            1.0
            - adaptive_score.max_estimated_work_s
            / static_score.max_estimated_work_s
            if static_score.max_estimated_work_s > 0
            else 0.0
        ),
        "boundary_displacement_levels": adaptive_score.boundary_displacement_levels,
        "left_zone_heights": "/".join(str(value) for value in left_heights),
        "right_zone_heights": "/".join(str(value) for value in right_heights),
        "active_reader_levels": "/".join(
            str(region.reader_level) for region in layout
        ),
        "shuttle_count": config.zone_count,
        "reader_count": config.zone_count,
    }


def _aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[float, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(float(row["hot_zone_fraction_target"]), []).append(row)
    identity = {
        "seed",
        "hot_zone_fraction_target",
        "left_zone_heights",
        "right_zone_heights",
        "active_reader_levels",
    }
    aggregates = []
    for fraction, group in sorted(groups.items()):
        aggregate: dict[str, Any] = {
            "hot_zone_fraction_target": fraction,
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
        aggregates.append(aggregate)
    return aggregates


def _findings(
    config: AdaptiveZoneStudyConfig,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    balanced = min(rows, key=lambda row: row["hot_zone_fraction_target"])
    maximum = max(rows, key=lambda row: row["hot_zone_fraction_target"])
    return {
        "balanced": {
            "request_skew": balanced["hot_zone_fraction_target"],
            "drain_speedup": balanced["drain_speedup_mean"],
            "throughput_improvement": balanced["throughput_improvement_mean"],
            "boundary_displacement_levels": balanced[
                "boundary_displacement_levels_mean"
            ],
        },
        "maximum_skew": {
            "request_skew": maximum["hot_zone_fraction_target"],
            "drain_speedup": maximum["drain_speedup_mean"],
            "throughput_improvement": maximum["throughput_improvement_mean"],
            "static_stranded_capacity_share": maximum[
                "static_stranded_capacity_share_mean"
            ],
            "adaptive_stranded_capacity_share": maximum[
                "adaptive_stranded_capacity_share_mean"
            ],
            "static_gap_to_ideal": maximum["static_gap_to_ideal_mean"],
            "adaptive_gap_to_ideal": maximum["adaptive_gap_to_ideal_mean"],
        },
        "interpretation_guardrail": (
            "This is a batch-oracle upper bound with zero boundary reconfiguration cost, "
            "not an online adaptive-zone policy."
        ),
        "reader_policy": (
            "Each region selects one midpoint-level reader from a fully populated read rack; "
            "both policies retain eight active readers and eight shuttles."
        ),
    }


def _layout_json(layout: tuple[ZoneRegion, ...]) -> list[dict[str, Any]]:
    return [asdict(region) | {"height": region.height} for region in layout]


def _max_mean_ratio(values: list[float]) -> float:
    average = mean(values) if values else 0.0
    return max(values, default=0.0) / average if average > 0 else 0.0


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
    config: AdaptiveZoneStudyConfig,
    result: AdaptiveZoneStudyResult,
) -> None:
    balanced = result.findings["balanced"]
    maximum = result.findings["maximum_skew"]
    lines = [
        "# Static Equal-size vs. Adaptive Work-balanced Zones",
        "",
        "## Research question",
        "",
        "With the same merged workload, eight shuttles, and eight active readers, how much "
        "capacity does equal-area static ownership strand, and how much can physically "
        "contiguous adaptive boundaries recover?",
        "",
        "## Controlled setup",
        "",
        f"- {config.workload.batch_size:,} logical requests per batch, "
        f"{config.workload.request_size_bytes / MIB:.0f} MiB each.",
        f"- {len(config.seeds)} paired seeds per skew point.",
        "- Batch-wide platter merge is always enabled.",
        "- Four positive-height contiguous rectangular zones per panel side.",
        "- No work stealing, prediction, Zipf distribution, or reconfiguration cost.",
        "- Adaptive boundaries observe the complete merged batch and therefore represent an upper bound.",
        "",
        "## Main results",
        "",
        f"- At balanced {balanced['request_skew'] * 100:.1f}% request share, adaptive drain "
        f"speedup is {balanced['drain_speedup']:.3f}x and throughput improvement is "
        f"{balanced['throughput_improvement']:.3f}x.",
        f"- At {maximum['request_skew'] * 100:.1f}% request skew, adaptive drain speedup is "
        f"{maximum['drain_speedup']:.3f}x and throughput improvement is "
        f"{maximum['throughput_improvement']:.3f}x.",
        f"- Static stranded capacity is {maximum['static_stranded_capacity_share'] * 100:.1f}%; "
        f"adaptive stranded capacity is {maximum['adaptive_stranded_capacity_share'] * 100:.1f}%.",
        f"- The system-drain gap to each policy's own work-conserving lower bound changes from "
        f"{maximum['static_gap_to_ideal']:.2f}x to {maximum['adaptive_gap_to_ideal']:.2f}x.",
        "",
        "## Interpretation",
        "",
        "The paired trace check ensures that any difference comes from ownership and reader "
        "assignment, not from fewer platter services. The adaptive result is intentionally an "
        "upper bound: a later study must account for boundary movement, control frequency, and "
        "time-varying workloads before claiming an implementable online gain.",
        "",
        "## Validation",
        "",
        f"- {result.validation['checked_runs']} paired runs preserved merged platter IDs, "
        "logical request count, bytes, side, level, and slot.",
        "- Every layout contains eight non-overlapping zones, eight shuttles, and eight active readers.",
        "- The equal-size static layout is a legal optimizer candidate.",
        "",
        "## Figure guide",
        "",
        "- `fig1_static_vs_adaptive_performance`: throughput and full-cycle drain time.",
        "- `fig2_imbalance_and_stranded_capacity`: exact zone-work imbalance and idle capacity.",
        "- `fig3_gap_to_work_conserving_ideal`: system drain relative to each policy's lower bound.",
        "- `fig4_representative_layout`: equal-size and adaptive panel layouts at maximum skew.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_figures(
    result: AdaptiveZoneStudyResult,
    figures_dir: Path,
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(Path("results/.mplconfig").resolve()))
    os.environ.setdefault("XDG_CACHE_HOME", str(Path("results/.cache").resolve()))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

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
    rows = sorted(result.aggregate_rows, key=lambda row: row["hot_zone_fraction_target"])
    x = [row["hot_zone_fraction_target"] * 100 for row in rows]

    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.0))
    axes[0].errorbar(
        x,
        [row["static_throughput_req_per_s_mean"] for row in rows],
        yerr=[row["static_throughput_req_per_s_ci95"] for row in rows],
        color="#C44E52",
        marker="o",
        capsize=3,
        label="Static equal-size",
    )
    axes[0].errorbar(
        x,
        [row["adaptive_throughput_req_per_s_mean"] for row in rows],
        yerr=[row["adaptive_throughput_req_per_s_ci95"] for row in rows],
        color="#2E8B57",
        marker="s",
        capsize=3,
        label="Adaptive work-balanced",
    )
    axes[0].set_ylabel("Logical throughput (requests/s)")
    axes[1].plot(
        x,
        [row["static_system_drain_s_mean"] / 3600 for row in rows],
        color="#C44E52",
        marker="o",
        label="Static equal-size",
    )
    axes[1].plot(
        x,
        [row["adaptive_system_drain_s_mean"] / 3600 for row in rows],
        color="#2E8B57",
        marker="s",
        label="Adaptive work-balanced",
    )
    axes[1].set_ylabel("Full-cycle system drain (hours)")
    for ax in axes:
        ax.set_xlabel("Requests assigned to original hot zone (%)")
        ax.grid(axis="y", alpha=0.25)
        ax.legend(frameon=False)
    fig.suptitle("Same merged workload and hardware, different ownership boundaries")
    fig.tight_layout()
    _save(fig, figures_dir, "fig1_static_vs_adaptive_performance")

    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.0))
    axes[0].plot(
        x,
        [row["static_zone_work_max_mean_ratio_mean"] for row in rows],
        color="#C44E52",
        marker="o",
        label="Static equal-size",
    )
    axes[0].plot(
        x,
        [row["adaptive_zone_work_max_mean_ratio_mean"] for row in rows],
        color="#2E8B57",
        marker="s",
        label="Adaptive work-balanced",
    )
    axes[0].set_ylabel("Maximum / mean exact zone work")
    axes[1].plot(
        x,
        [row["static_stranded_capacity_share_mean"] * 100 for row in rows],
        color="#C44E52",
        marker="o",
        label="Static equal-size",
    )
    axes[1].plot(
        x,
        [row["adaptive_stranded_capacity_share_mean"] * 100 for row in rows],
        color="#2E8B57",
        marker="s",
        label="Adaptive work-balanced",
    )
    axes[1].set_ylabel("Stranded zone-time capacity (%)")
    for ax in axes:
        ax.set_xlabel("Requests assigned to original hot zone (%)")
        ax.grid(axis="y", alpha=0.25)
        ax.legend(frameon=False)
    fig.suptitle("Adaptive boundaries reduce fixed-owner imbalance")
    fig.tight_layout()
    _save(fig, figures_dir, "fig2_imbalance_and_stranded_capacity")

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.plot(
        x,
        [row["static_gap_to_ideal_mean"] for row in rows],
        color="#C44E52",
        marker="o",
        label="Static equal-size",
    )
    ax.plot(
        x,
        [row["adaptive_gap_to_ideal_mean"] for row in rows],
        color="#2E8B57",
        marker="s",
        label="Adaptive work-balanced",
    )
    ax.axhline(1.0, color="#555555", linestyle=":", label="Work-conserving lower bound")
    ax.set_xlabel("Requests assigned to original hot zone (%)")
    ax.set_ylabel("System drain / own productive-work lower bound")
    ax.set_title("Remaining gap to ideal work conservation")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)
    _save(fig, figures_dir, "fig3_gap_to_work_conserving_ideal")

    fig, axes = plt.subplots(1, 2, figsize=(8.8, 5.2))
    for ax, title, layout_key, rows_key in (
        (axes[0], "Static equal-size", "static_layout", "static_zone_rows"),
        (axes[1], "Adaptive work-balanced", "adaptive_layout", "adaptive_zone_rows"),
    ):
        layout = result.representative[layout_key]
        zone_rows = {
            int(row["zone_id"]): row for row in result.representative[rows_key]
        }
        total_work = sum(float(row["active_cycle_s"]) for row in zone_rows.values())
        for region in layout:
            x0 = 0.0 if region["side"] == "left" else 1.05
            height = region["end_level"] - region["start_level"]
            rect = Rectangle(
                (x0, region["start_level"]),
                0.95,
                height,
                facecolor=(
                    "#F4D7D7"
                    if region["side"] == result.representative["hot_side"]
                    and region["start_level"] < result.representative["hot_end_level"]
                    and region["end_level"] > result.representative["hot_start_level"]
                    else "#DCE9DF"
                ),
                edgecolor="#303030",
                linewidth=1.0,
            )
            ax.add_patch(rect)
            share = (
                float(zone_rows[region["zone_id"]]["active_cycle_s"]) / total_work
                if total_work > 0
                else 0.0
            )
            ax.text(
                x0 + 0.475,
                region["start_level"] + height / 2,
                f"{share * 100:.1f}%",
                ha="center",
                va="center",
                fontsize=8,
            )
        ax.set_xlim(0, 2.0)
        ax.set_ylim(8, 0)
        ax.set_xticks([0.475, 1.525], ["Left", "Right"])
        ax.set_yticks(range(9))
        ax.set_ylabel("Panel level")
        ax.set_title(title)
        ax.set_aspect("equal")
    fig.suptitle(
        f"Representative {result.representative['hot_zone_fraction'] * 100:.0f}% skew: "
        "share of exact work per zone"
    )
    fig.tight_layout()
    _save(fig, figures_dir, "fig4_representative_layout")


def _save(fig: Any, figures_dir: Path, stem: str) -> None:
    fig.savefig(figures_dir / f"{stem}.png", dpi=220, bbox_inches="tight")
    fig.savefig(figures_dir / f"{stem}.pdf", bbox_inches="tight")
    import matplotlib.pyplot as plt

    plt.close(fig)
