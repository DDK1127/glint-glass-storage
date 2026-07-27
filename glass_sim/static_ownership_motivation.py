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

from .panel_static_zone import (
    MIB,
    PanelGeometryConfig,
    PanelMovementConfig,
    PanelRequest,
    PanelStaticZoneConfig,
    PanelStaticZoneSimulator,
    PanelTimingConfig,
    PanelWorkloadConfig,
    merge_panel_requests,
)
from .paths import portable_path, repository_root_for_config


UNIQUE_MODE = "unique_tasks"
MERGED_MODE = "logical_requests_merged"
MODE_ORDER = (UNIQUE_MODE, MERGED_MODE)


@dataclass(frozen=True)
class StaticOwnershipWorkloadConfig:
    task_count: int
    logical_request_count: int
    request_size_bytes: int
    owner_distributions: dict[str, tuple[int, ...]]
    baseline_scenario: str = "balanced"
    timeline_scenario: str = "moderate"

    def validate(self, zone_count: int, local_capacity: int) -> None:
        if self.task_count <= 0:
            raise ValueError("workload.task_count must be positive")
        if self.logical_request_count < self.task_count:
            raise ValueError(
                "workload.logical_request_count must be at least task_count"
            )
        if self.request_size_bytes <= 0:
            raise ValueError("workload.request_size_bytes must be positive")
        if not self.owner_distributions:
            raise ValueError("workload.owner_distributions cannot be empty")
        if self.baseline_scenario not in self.owner_distributions:
            raise ValueError("workload.baseline_scenario is not defined")
        if self.timeline_scenario not in self.owner_distributions:
            raise ValueError("workload.timeline_scenario is not defined")
        for name, counts in self.owner_distributions.items():
            if len(counts) != zone_count:
                raise ValueError(f"{name} must define exactly {zone_count} owners")
            if sum(counts) != self.task_count:
                raise ValueError(f"{name} must contain exactly {self.task_count} tasks")
            if min(counts) <= 0:
                raise ValueError(f"{name} must assign work to every owner")
            if max(counts) > local_capacity:
                raise ValueError(f"{name} exceeds one partition's platter capacity")


@dataclass(frozen=True)
class StaticOwnershipMotivationConfig:
    output_dir: Path
    seeds: tuple[int, ...]
    geometry: PanelGeometryConfig
    movement: PanelMovementConfig
    timing: PanelTimingConfig
    workload: StaticOwnershipWorkloadConfig

    @property
    def zone_count(self) -> int:
        return (
            self.geometry.levels // self.geometry.zone_height_racks
        ) * 2

    def validate(self) -> None:
        self.geometry.validate()
        self.movement.validate()
        self.timing.validate()
        if not self.seeds:
            raise ValueError("seeds cannot be empty")
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds must be unique")
        if self.zone_count != 8:
            raise ValueError("this experiment requires exactly eight static partitions")
        local_capacity = (
            self.geometry.zone_height_racks * self.geometry.slots_per_half
        )
        self.workload.validate(self.zone_count, local_capacity)

    def to_json_dict(self) -> dict[str, Any]:
        workload = asdict(self.workload)
        workload["owner_distributions"] = {
            name: list(counts)
            for name, counts in self.workload.owner_distributions.items()
        }
        return {
            "output_dir": portable_path(self.output_dir),
            "seeds": list(self.seeds),
            "geometry": asdict(self.geometry),
            "movement": asdict(self.movement),
            "timing": asdict(self.timing),
            "workload": workload,
            "experiment_scope": {
                "static_non_overlapping_ownership": True,
                "adaptive_zones": False,
                "work_stealing": False,
                "zipf": False,
                "real_trace": False,
            },
        }


@dataclass(frozen=True)
class StaticOwnershipMotivationResult:
    run_rows: list[dict[str, Any]]
    aggregate_rows: list[dict[str, Any]]
    partition_rows: list[dict[str, Any]]
    validation: dict[str, Any]
    findings: dict[str, Any]
    representative: dict[str, Any]


def load_static_ownership_motivation_config(
    path: str | Path,
) -> StaticOwnershipMotivationConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    base_dir = repository_root_for_config(config_path)
    output_dir = Path(raw["output_dir"]).expanduser()
    if not output_dir.is_absolute():
        output_dir = (base_dir / output_dir).resolve()
    workload_raw = dict(raw["workload"])
    workload_raw["owner_distributions"] = {
        str(name): tuple(int(value) for value in counts)
        for name, counts in workload_raw["owner_distributions"].items()
    }
    config = StaticOwnershipMotivationConfig(
        output_dir=output_dir,
        seeds=tuple(int(value) for value in raw["seeds"]),
        geometry=PanelGeometryConfig(**raw["geometry"]),
        movement=PanelMovementConfig(**raw["movement"]),
        timing=PanelTimingConfig(**raw["timing"]),
        workload=StaticOwnershipWorkloadConfig(**workload_raw),
    )
    config.validate()
    return config


def build_paired_unique_tasks(
    simulator: PanelStaticZoneSimulator,
    owner_counts: tuple[int, ...],
    task_count: int,
    request_size_bytes: int,
    seed: int,
) -> list[PanelRequest]:
    if len(owner_counts) != simulator.zone_count or sum(owner_counts) != task_count:
        raise ValueError("owner counts must match the simulator and task count")
    local_capacity = (
        simulator.geometry.zone_height_racks
        * simulator.geometry.slots_per_half
    )
    if task_count > local_capacity:
        raise ValueError(
            "paired unique templates require task_count <= local partition capacity"
        )

    templates = list(range(local_capacity))
    random.Random(seed + 101).shuffle(templates)
    templates = templates[:task_count]

    owners = [
        zone_id
        for zone_id, count in enumerate(owner_counts)
        for _ in range(count)
    ]
    random.Random(seed + 211).shuffle(owners)

    requests = []
    for index, (template, zone_id) in enumerate(zip(templates, owners)):
        local_level, reader_distance_slot = divmod(
            template,
            simulator.geometry.slots_per_half,
        )
        if zone_id % 2 == 0:
            slot_in_half = reader_distance_slot
        else:
            slot_in_half = (
                simulator.geometry.slots_per_half - 1 - reader_distance_slot
            )
        requests.append(
            simulator.make_request(
                request_index=index,
                zone_id=zone_id,
                local_level=local_level,
                slot_in_half=slot_in_half,
                size_bytes=request_size_bytes,
            )
        )
    return requests


def expand_logical_requests(
    targets: list[PanelRequest],
    logical_request_count: int,
    request_size_bytes: int,
    seed: int,
) -> list[PanelRequest]:
    if not targets:
        raise ValueError("targets cannot be empty")
    if logical_request_count < len(targets):
        raise ValueError("logical_request_count cannot be smaller than targets")
    base, extra = divmod(logical_request_count, len(targets))
    multiplicities = [base + 1] * extra + [base] * (len(targets) - extra)
    random.Random(seed + 307).shuffle(multiplicities)

    logical = []
    request_index = 0
    for target, multiplicity in zip(targets, multiplicities):
        for _ in range(multiplicity):
            logical.append(
                replace(
                    target,
                    request_index=request_index,
                    size_bytes=request_size_bytes,
                    merged_request_count=1,
                )
            )
            request_index += 1
    return logical


def reader_relative_signature(
    request: PanelRequest,
    slots_per_half: int,
    zone_height_racks: int,
) -> tuple[int, int]:
    local_level = request.level - (
        request.row_id * zone_height_racks
    )
    reader_distance_slot = (
        request.slot_in_half
        if request.side == "left"
        else slots_per_half - 1 - request.slot_in_half
    )
    return local_level, reader_distance_slot


def run_static_ownership_motivation(
    config: StaticOwnershipMotivationConfig,
) -> StaticOwnershipMotivationResult:
    config.validate()
    run_rows: list[dict[str, Any]] = []
    partition_rows: list[dict[str, Any]] = []
    failures: list[str] = []
    representative: dict[str, Any] = {}

    for seed in config.seeds:
        expected_signatures: list[tuple[int, int]] | None = None
        expected_intrinsic_costs: list[float] | None = None
        expected_multiplicities: list[int] | None = None
        for scenario, owner_counts in config.workload.owner_distributions.items():
            unique_simulator = PanelStaticZoneSimulator(
                _panel_config(config, seed, request_merge=False)
            )
            unique_tasks = build_paired_unique_tasks(
                unique_simulator,
                owner_counts,
                config.workload.task_count,
                config.workload.request_size_bytes,
                seed,
            )
            signatures = [
                reader_relative_signature(
                    request,
                    config.geometry.slots_per_half,
                    config.geometry.zone_height_racks,
                )
                for request in unique_tasks
            ]
            if expected_signatures is None:
                expected_signatures = signatures
            elif signatures != expected_signatures:
                failures.append(f"seed {seed} {scenario}: local coordinates are not paired")
            intrinsic_costs = [
                _isolated_service_cost_s(unique_simulator, request)
                for request in unique_tasks
            ]
            if expected_intrinsic_costs is None:
                expected_intrinsic_costs = intrinsic_costs
            elif intrinsic_costs != expected_intrinsic_costs:
                failures.append(
                    f"seed {seed} {scenario}: intrinsic service costs are not paired"
                )
            _validate_unique_tasks(
                unique_tasks,
                owner_counts,
                config,
                f"seed {seed} {scenario}",
                failures,
            )

            unique_result = unique_simulator.run(unique_tasks)
            _append_result(
                run_rows,
                partition_rows,
                config,
                scenario,
                UNIQUE_MODE,
                seed,
                owner_counts,
                unique_result,
            )

            logical_simulator = PanelStaticZoneSimulator(
                _panel_config(config, seed, request_merge=True)
            )
            logical_targets = build_paired_unique_tasks(
                logical_simulator,
                owner_counts,
                config.workload.task_count,
                config.workload.request_size_bytes,
                seed,
            )
            logical = expand_logical_requests(
                logical_targets,
                config.workload.logical_request_count,
                config.workload.request_size_bytes,
                seed,
            )
            merged = merge_panel_requests(logical)
            multiplicities = [request.merged_request_count for request in merged]
            if expected_multiplicities is None:
                expected_multiplicities = multiplicities
            elif multiplicities != expected_multiplicities:
                failures.append(f"seed {seed} {scenario}: merge multiplicities are not paired")
            _validate_merge(
                logical,
                merged,
                owner_counts,
                config,
                f"seed {seed} {scenario}",
                failures,
            )

            merged_result = logical_simulator.run(merged)
            _append_result(
                run_rows,
                partition_rows,
                config,
                scenario,
                MERGED_MODE,
                seed,
                owner_counts,
                merged_result,
            )
            if (
                seed == config.seeds[0]
                and scenario == config.workload.timeline_scenario
            ):
                representative = {
                    "seed": seed,
                    "scenario": scenario,
                    "mode": UNIQUE_MODE,
                    "system_drain_s": unique_result.summary["system_drain_s"],
                    "partition_rows": [
                        {
                            "partition_id": row["zone_id"],
                            "task_count": row["glass_service_count"],
                            "active_work_s": row["active_cycle_s"],
                            "completion_s": row["completion_s"],
                        }
                        for row in unique_result.zone_rows
                    ],
                }

    _normalize_to_balanced(config, run_rows)
    _validate_resource_counts(config, run_rows, failures)
    aggregate_rows = _aggregate(run_rows)
    _validate_monotonicity(config, aggregate_rows, failures)
    if failures:
        raise RuntimeError(
            "static-ownership motivation validation failed: "
            + "; ".join(failures)
        )
    validation = {
        "passed": True,
        "checked_runs": len(run_rows),
        "paired_seeds": len(config.seeds),
        "paired_reader_relative_coordinates": True,
        "paired_intrinsic_service_costs": True,
        "paired_request_multiplicities": True,
        "exact_owner_counts": True,
        "unique_non_overlapping_platters": True,
        "logical_requests_preserved": config.workload.logical_request_count,
        "merged_physical_tasks": config.workload.task_count,
        "fixed_shuttles": config.zone_count,
        "fixed_active_readers": config.zone_count,
        "monotonic_completion_and_stranding": True,
        "failures": [],
    }
    return StaticOwnershipMotivationResult(
        run_rows=run_rows,
        aggregate_rows=aggregate_rows,
        partition_rows=partition_rows,
        validation=validation,
        findings=_build_findings(config, aggregate_rows),
        representative=representative,
    )


def write_static_ownership_motivation_outputs(
    config: StaticOwnershipMotivationConfig,
    result: StaticOwnershipMotivationResult,
) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    _write_rows(config.output_dir / "run_summary.csv", result.run_rows)
    _write_rows(config.output_dir / "aggregate_summary.csv", result.aggregate_rows)
    _write_rows(config.output_dir / "partition_summary.csv", result.partition_rows)
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
    _write_chinese_report(
        config.output_dir / "STATIC_OWNERSHIP_MOTIVATION_ANALYSIS_ZH.md",
        config,
        result,
    )
    figures_dir = config.output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    _write_figures(config, result, figures_dir)


def _panel_config(
    config: StaticOwnershipMotivationConfig,
    seed: int,
    request_merge: bool,
) -> PanelStaticZoneConfig:
    batch_size = (
        config.workload.logical_request_count
        if request_merge
        else config.workload.task_count
    )
    return PanelStaticZoneConfig(
        output_dir=config.output_dir,
        seed=seed,
        geometry=config.geometry,
        movement=config.movement,
        timing=config.timing,
        workload=PanelWorkloadConfig(
            batch_size=batch_size,
            request_size_bytes=config.workload.request_size_bytes,
            placement="uniform_round_robin",
            request_merge=request_merge,
        ),
    )


def _isolated_service_cost_s(
    simulator: PanelStaticZoneSimulator,
    request: PanelRequest,
) -> float:
    reader_to_glass_s = simulator._move_time_s(
        request.reader_level,
        request.reader_slot_in_half,
        request.level,
        request.slot_in_half,
    )
    return (
        3.0 * reader_to_glass_s
        + simulator.timing.storage_pick_s
        + simulator.timing.reader_load_s
        + simulator._read_time_s(request.size_bytes)
        + simulator.timing.reader_unload_s
        + simulator.timing.storage_place_s
    )


def _validate_unique_tasks(
    requests: list[PanelRequest],
    owner_counts: tuple[int, ...],
    config: StaticOwnershipMotivationConfig,
    label: str,
    failures: list[str],
) -> None:
    observed = tuple(
        sum(request.zone_id == zone_id for request in requests)
        for zone_id in range(config.zone_count)
    )
    if len(requests) != config.workload.task_count:
        failures.append(f"{label}: unique task count changed")
    if observed != owner_counts:
        failures.append(f"{label}: owner counts are {observed}, expected {owner_counts}")
    if len({request.platter_id for request in requests}) != len(requests):
        failures.append(f"{label}: platter ownership overlaps or repeats")
    if any(
        request.size_bytes != config.workload.request_size_bytes
        for request in requests
    ):
        failures.append(f"{label}: request size changed")


def _validate_merge(
    logical: list[PanelRequest],
    merged: list[PanelRequest],
    owner_counts: tuple[int, ...],
    config: StaticOwnershipMotivationConfig,
    label: str,
    failures: list[str],
) -> None:
    if len(logical) != config.workload.logical_request_count:
        failures.append(f"{label}: logical request count changed")
    if len(merged) != config.workload.task_count:
        failures.append(f"{label}: merge did not produce exactly 640 tasks")
    if sum(request.merged_request_count for request in merged) != len(logical):
        failures.append(f"{label}: merge lost logical requests")
    if sum(request.size_bytes for request in merged) != sum(
        request.size_bytes for request in logical
    ):
        failures.append(f"{label}: merge changed total bytes")
    observed = tuple(
        sum(request.zone_id == zone_id for request in merged)
        for zone_id in range(config.zone_count)
    )
    if observed != owner_counts:
        failures.append(f"{label}: merge changed owner counts")
    allowed = {
        config.workload.logical_request_count // config.workload.task_count,
        math.ceil(
            config.workload.logical_request_count / config.workload.task_count
        ),
    }
    if set(request.merged_request_count for request in merged) != allowed:
        failures.append(f"{label}: target multiplicities are not floor/ceiling paired")


def _append_result(
    run_rows: list[dict[str, Any]],
    partition_rows: list[dict[str, Any]],
    config: StaticOwnershipMotivationConfig,
    scenario: str,
    mode: str,
    seed: int,
    owner_counts: tuple[int, ...],
    result: Any,
) -> None:
    summary = result.summary
    work = [float(row["active_cycle_s"]) for row in result.zone_rows]
    average_work = mean(work)
    row = {
        "scenario": scenario,
        "mode": mode,
        "seed": seed,
        "logical_request_count": summary["request_count"],
        "physical_task_count": summary["service_operation_count"],
        "logical_bytes": sum(detail.size_bytes for detail in result.details),
        "target_busiest_owner_amplification": (
            max(owner_counts) / mean(owner_counts)
        ),
        "busiest_owner_work_over_mean": (
            max(work) / average_work if average_work > 0 else 0.0
        ),
        "system_drain_s": summary["system_drain_s"],
        "drive_makespan_s": summary["drive_makespan_s"],
        "ideal_balanced_work_s": summary[
            "ideal_balanced_cycle_lower_bound_s"
        ],
        "ownership_slowdown_vs_ideal": summary[
            "ownership_slowdown_vs_ideal"
        ],
        "capacity_efficiency": summary["static_capacity_efficiency"],
        "stranded_capacity_share": summary["stranded_capacity_share"],
        "stranded_shuttle_time_s": summary["stranded_capacity_s"],
        "productive_cycle_s": summary["productive_cycle_s"],
        "shuttle_count": summary["shuttle_count"],
        "reader_count": summary["reader_count"],
        "owner_counts": "/".join(str(value) for value in owner_counts),
        "system_drain_over_balanced": 0.0,
    }
    run_rows.append(row)
    for zone in result.zone_rows:
        partition_rows.append(
            {
                "scenario": scenario,
                "mode": mode,
                "seed": seed,
                "partition_id": zone["zone_id"],
                "task_count": zone["glass_service_count"],
                "logical_request_count": zone["logical_request_count"],
                "completion_s": zone["completion_s"],
                "active_work_s": zone["active_cycle_s"],
                "idle_tail_s": summary["system_drain_s"] - zone["completion_s"],
            }
        )


def _normalize_to_balanced(
    config: StaticOwnershipMotivationConfig,
    rows: list[dict[str, Any]],
) -> None:
    balanced = {
        (row["mode"], row["seed"]): float(row["system_drain_s"])
        for row in rows
        if row["scenario"] == config.workload.baseline_scenario
    }
    for row in rows:
        baseline = balanced[(row["mode"], row["seed"])]
        row["system_drain_over_balanced"] = (
            float(row["system_drain_s"]) / baseline
        )


def _validate_resource_counts(
    config: StaticOwnershipMotivationConfig,
    rows: list[dict[str, Any]],
    failures: list[str],
) -> None:
    for row in rows:
        label = f"{row['mode']} {row['scenario']} seed {row['seed']}"
        if row["physical_task_count"] != config.workload.task_count:
            failures.append(f"{label}: physical task count changed")
        expected_logical = (
            config.workload.logical_request_count
            if row["mode"] == MERGED_MODE
            else config.workload.task_count
        )
        if row["logical_request_count"] != expected_logical:
            failures.append(f"{label}: logical request count changed")
        if (
            row["shuttle_count"] != config.zone_count
            or row["reader_count"] != config.zone_count
        ):
            failures.append(f"{label}: resource count changed")


def _aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((str(row["scenario"]), str(row["mode"])), []).append(row)
    identity = {"scenario", "mode", "seed", "owner_counts"}
    aggregates = []
    for (scenario, mode), group in groups.items():
        aggregate: dict[str, Any] = {
            "scenario": scenario,
            "mode": mode,
            "run_count": len(group),
            "owner_counts": group[0]["owner_counts"],
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


def _validate_monotonicity(
    config: StaticOwnershipMotivationConfig,
    rows: list[dict[str, Any]],
    failures: list[str],
) -> None:
    scenario_order = list(config.workload.owner_distributions)
    expected = {
        name: max(counts) / mean(counts)
        for name, counts in config.workload.owner_distributions.items()
    }
    for name, target in expected.items():
        if name == "balanced" and not math.isclose(target, 1.0):
            failures.append("balanced target amplification is not 1x")
        if name == "moderate" and not math.isclose(target, 2.0):
            failures.append("moderate target amplification is not 2x")
        if name == "strong" and not math.isclose(target, 4.0):
            failures.append("strong target amplification is not 4x")
    for mode in MODE_ORDER:
        series = [
            next(
                row
                for row in rows
                if row["mode"] == mode and row["scenario"] == scenario
            )
            for scenario in scenario_order
        ]
        drains = [float(row["system_drain_over_balanced_mean"]) for row in series]
        stranded = [float(row["stranded_capacity_share_mean"]) for row in series]
        if any(right + 1e-9 < left for left, right in zip(drains, drains[1:])):
            failures.append(f"{mode}: completion is not monotonic")
        if any(
            right + 1e-9 < left
            for left, right in zip(stranded, stranded[1:])
        ):
            failures.append(f"{mode}: stranded capacity is not monotonic")


def _build_findings(
    config: StaticOwnershipMotivationConfig,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    by_key = {
        (row["mode"], row["scenario"]): row
        for row in rows
    }
    scenarios = {}
    for scenario in config.workload.owner_distributions:
        unique = by_key[(UNIQUE_MODE, scenario)]
        merged = by_key[(MERGED_MODE, scenario)]
        scenarios[scenario] = {
            "owner_counts": unique["owner_counts"],
            "target_busiest_owner_amplification": unique[
                "target_busiest_owner_amplification_mean"
            ],
            "unique_tasks": {
                "system_drain_over_balanced": unique[
                    "system_drain_over_balanced_mean"
                ],
                "ownership_slowdown_vs_ideal": unique[
                    "ownership_slowdown_vs_ideal_mean"
                ],
                "capacity_efficiency": unique["capacity_efficiency_mean"],
                "stranded_capacity_share": unique[
                    "stranded_capacity_share_mean"
                ],
            },
            "logical_requests_merged": {
                "system_drain_over_balanced": merged[
                    "system_drain_over_balanced_mean"
                ],
                "ownership_slowdown_vs_ideal": merged[
                    "ownership_slowdown_vs_ideal_mean"
                ],
                "capacity_efficiency": merged["capacity_efficiency_mean"],
                "stranded_capacity_share": merged[
                    "stranded_capacity_share_mean"
                ],
            },
        }
    return {
        "scenarios": scenarios,
        "causal_claim": (
            "Equal-area static ownership does not guarantee equal post-merge work; "
            "the busiest owner determines batch completion while other shuttle-time is stranded."
        ),
        "evidence_boundary": (
            "This controlled mechanism experiment does not estimate how often these "
            "owner distributions occur in production Silica deployments."
        ),
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


def _write_chinese_report(
    path: Path,
    config: StaticOwnershipMotivationConfig,
    result: StaticOwnershipMotivationResult,
) -> None:
    scenarios = result.findings["scenarios"]
    lines = [
        "# Static Ownership 動機實驗",
        "",
        "## 研究問題",
        "",
        "等面積 partition 可以平均分配儲存空間，但它是否也能讓每個 batch "
        "在 merge 後的 physical work 平均？",
        "",
        "## 控制方式",
        "",
        f"- 固定 {config.zone_count} 個 non-overlapping partitions、"
        f"{config.zone_count} 個 shuttles 與 {config.zone_count} 個 active readers。",
        f"- 每個 case 都有 {config.workload.task_count} 個 "
        f"{config.workload.request_size_bytes / MIB:.0f} MiB unique platter targets，"
        f"使用 {len(config.seeds)} 個 paired seeds。",
        "- 三個 cases 使用相同的 reader-relative local coordinates；只改變 target 的 owner。",
        f"- 補充實驗把 {config.workload.logical_request_count:,} 個 logical requests "
        f"平均配對到同一批 {config.workload.task_count} 個 targets，再做 batch-wide merge。",
        "- 不包含 Adaptive、work stealing、Zipf、boundary movement 或真實 trace。",
        "",
        "## 結果",
        "",
    ]
    for scenario, values in scenarios.items():
        unique = values["unique_tasks"]
        merged = values["logical_requests_merged"]
        lines.extend(
            [
                f"### {scenario.title()} `{values['owner_counts']}`",
                "",
                f"- Busiest-owner task amplification："
                f"{values['target_busiest_owner_amplification']:.2f}x。",
                f"- Unique-task system drain / balanced："
                f"{unique['system_drain_over_balanced']:.2f}x；"
                f"stranded capacity：{unique['stranded_capacity_share'] * 100:.1f}%。",
                f"- Logical-request-plus-merge system drain / balanced："
                f"{merged['system_drain_over_balanced']:.2f}x；"
                f"stranded capacity：{merged['stranded_capacity_share'] * 100:.1f}%。",
                "",
            ]
        )
    lines.extend(
        [
            "## 解讀",
            "",
            "這個結果隔離出 static ownership 的基本機制：總 physical work 沒有減少，"
            "但工作集中到單一 owner 後，其他 partition 的 shuttle 提早 idle，batch "
            "仍必須等待最忙 owner 完成。Request merge 只合併同一 platter 的重複請求，"
            "不會把 merge 後的 platter task 重新分配給其他 owner。",
            "",
            "本實驗只證明這個 causal mechanism，不宣稱 moderate 或 strong distribution "
            "在 production Silica 中出現的頻率。真實 placement 與 trace prevalence "
            "應在下一階段另外驗證。",
            "",
            "## 圖表",
            "",
            "- `fig1_equal_area_unequal_work`：normalized completion 與 moderate timeline。",
            "- `fig2_merge_does_not_balance_ownership`：merge 前後的 ownership slowdown 與 stranded capacity。",
            "",
            "## 驗證",
            "",
            f"- {result.validation['checked_runs']} runs 全部維持 "
            f"{config.workload.task_count} 個 physical tasks。",
            f"- Logical case 精確保留 {config.workload.logical_request_count:,} requests "
            f"並 merge 成 {config.workload.task_count} tasks。",
            "- 每片 platter 只有一個 owner，沒有 partition overlap。",
            "- Completion time 與 stranded capacity 隨 owner imbalance 單調增加。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_figures(
    config: StaticOwnershipMotivationConfig,
    result: StaticOwnershipMotivationResult,
    figures_dir: Path,
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(Path("results/.mplconfig").resolve()))
    os.environ.setdefault("XDG_CACHE_HOME", str(Path("results/.cache").resolve()))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

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
    scenario_order = list(config.workload.owner_distributions)
    unique = {
        row["scenario"]: row
        for row in result.aggregate_rows
        if row["mode"] == UNIQUE_MODE
    }
    colors = ["#4C9F70", "#D9903D", "#C44E52"]

    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.0))
    x = list(range(len(scenario_order)))
    axes[0].bar(
        x,
        [
            unique[name]["system_drain_over_balanced_mean"]
            for name in scenario_order
        ],
        yerr=[
            unique[name]["system_drain_over_balanced_ci95"]
            for name in scenario_order
        ],
        capsize=3,
        color=colors,
    )
    axes[0].set_xticks(x, [name.title() for name in scenario_order])
    axes[0].set_ylabel("System drain / balanced drain")
    axes[0].set_title("Equal area, unequal batch completion")
    axes[0].axhline(1.0, color="#5F6368", linestyle=":", linewidth=1)
    axes[0].grid(axis="y", alpha=0.25)

    representative = result.representative
    partition_rows = representative["partition_rows"]
    drain = float(representative["system_drain_s"])
    y = list(range(config.zone_count))
    completion = [row["completion_s"] / 3600 for row in partition_rows]
    idle = [(drain - row["completion_s"]) / 3600 for row in partition_rows]
    hot_owner = max(
        range(len(partition_rows)),
        key=lambda index: partition_rows[index]["task_count"],
    )
    active_colors = [
        "#C44E52" if index == hot_owner else "#4C9F70"
        for index in y
    ]
    axes[1].barh(y, completion, color=active_colors)
    axes[1].barh(
        y,
        idle,
        left=completion,
        color="#D9DEE5",
    )
    axes[1].set_yticks(y, [f"P{index}" for index in y])
    axes[1].invert_yaxis()
    axes[1].set_xlabel("Time (hours)")
    axes[1].set_title("Moderate skew leaves a long idle tail")
    axes[1].grid(axis="x", alpha=0.25)
    axes[1].legend(
        handles=[
            Patch(color="#C44E52", label="Busiest owner working"),
            Patch(color="#4C9F70", label="Cold owner working"),
            Patch(color="#D9DEE5", label="Idle while batch waits"),
        ],
        frameon=False,
        loc="lower right",
    )
    fig.suptitle("Static non-overlapping ownership serializes each partition")
    fig.tight_layout()
    _save(fig, figures_dir, "fig1_equal_area_unequal_work")

    aggregate = {
        (row["mode"], row["scenario"]): row
        for row in result.aggregate_rows
    }
    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.0))
    width = 0.36
    for offset, mode, color, label in (
        (-width / 2, UNIQUE_MODE, "#2F6B9A", "640 unique tasks"),
        (width / 2, MERGED_MODE, "#D9903D", "10,000 requests, then merge"),
    ):
        mode_rows = [aggregate[(mode, name)] for name in scenario_order]
        axes[0].bar(
            [value + offset for value in x],
            [row["ownership_slowdown_vs_ideal_mean"] for row in mode_rows],
            width=width,
            color=color,
            label=label,
        )
        axes[1].bar(
            [value + offset for value in x],
            [row["stranded_capacity_share_mean"] * 100 for row in mode_rows],
            width=width,
            color=color,
            label=label,
        )
    axes[0].set_ylabel("System drain / ideal balanced work")
    axes[1].set_ylabel("Stranded shuttle-time (%)")
    for ax in axes:
        ax.set_xticks(x, [name.title() for name in scenario_order])
        ax.grid(axis="y", alpha=0.25)
    axes[0].axhline(1.0, color="#5F6368", linestyle=":", linewidth=1)
    axes[0].set_title("Ownership remains the completion bottleneck")
    axes[1].set_title("Merge does not recover cold-owner capacity")
    axes[0].legend(frameon=False, loc="upper left")
    fig.suptitle("Batch-wide merge preserves owner-level imbalance")
    fig.tight_layout()
    _save(fig, figures_dir, "fig2_merge_does_not_balance_ownership")


def _save(fig: Any, figures_dir: Path, stem: str) -> None:
    fig.savefig(figures_dir / f"{stem}.png", dpi=220, bbox_inches="tight")
    fig.savefig(figures_dir / f"{stem}.pdf", bbox_inches="tight")
    import matplotlib.pyplot as plt

    plt.close(fig)
