from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import json
import math
import os
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from .panel_static_zone import (
    MIB,
    PanelGeometryConfig,
    PanelMovementConfig,
    PanelStaticZoneConfig,
    PanelStaticZoneSimulator,
    PanelTimingConfig,
    PanelWorkloadConfig,
    merge_panel_requests,
)
from .paths import portable_path, repository_root_for_config
from .static_ownership_motivation import (
    build_paired_unique_tasks,
    expand_logical_requests,
    reader_relative_signature,
)


@dataclass(frozen=True)
class StaticOwnershipThresholdWorkloadConfig:
    task_count: int
    logical_request_count: int
    request_size_bytes: int
    hot_owner: int
    hot_owner_task_counts: tuple[int, ...]

    def validate(self, zone_count: int, local_capacity: int) -> None:
        if self.task_count <= 0:
            raise ValueError("workload.task_count must be positive")
        if self.logical_request_count < self.task_count:
            raise ValueError(
                "workload.logical_request_count must be at least task_count"
            )
        if self.request_size_bytes <= 0:
            raise ValueError("workload.request_size_bytes must be positive")
        if not 0 <= self.hot_owner < zone_count:
            raise ValueError("workload.hot_owner must be a valid partition")
        if not self.hot_owner_task_counts:
            raise ValueError("workload.hot_owner_task_counts cannot be empty")
        if tuple(sorted(set(self.hot_owner_task_counts))) != (
            self.hot_owner_task_counts
        ):
            raise ValueError(
                "workload.hot_owner_task_counts must be unique and increasing"
            )
        balanced = self.task_count / zone_count
        if not math.isclose(self.hot_owner_task_counts[0], balanced):
            raise ValueError("the first sweep point must be exactly balanced")
        if self.hot_owner_task_counts[-1] > local_capacity:
            raise ValueError("the hottest owner exceeds local platter capacity")
        if any(
            count < balanced or count >= self.task_count
            for count in self.hot_owner_task_counts
        ):
            raise ValueError("hot-owner task counts are outside the sweep range")


@dataclass(frozen=True)
class StaticOwnershipThresholdConfig:
    output_dir: Path
    seeds: tuple[int, ...]
    geometry: PanelGeometryConfig
    movement: PanelMovementConfig
    timing: PanelTimingConfig
    workload: StaticOwnershipThresholdWorkloadConfig

    @property
    def zone_count(self) -> int:
        return (
            self.geometry.levels // self.geometry.zone_height_racks
        ) * 2

    def validate(self) -> None:
        self.geometry.validate()
        self.movement.validate()
        self.timing.validate()
        if not self.seeds or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds must be non-empty and unique")
        if self.zone_count != 8:
            raise ValueError("this experiment requires exactly eight partitions")
        self.workload.validate(
            self.zone_count,
            self.geometry.zone_height_racks
            * self.geometry.slots_per_half,
        )

    def to_json_dict(self) -> dict[str, Any]:
        workload = asdict(self.workload)
        workload["hot_owner_task_counts"] = list(
            self.workload.hot_owner_task_counts
        )
        return {
            "output_dir": portable_path(self.output_dir),
            "seeds": list(self.seeds),
            "geometry": asdict(self.geometry),
            "movement": asdict(self.movement),
            "timing": asdict(self.timing),
            "workload": workload,
            "experiment_scope": {
                "static_non_overlapping_ownership": True,
                "batch_wide_merge": True,
                "adaptive_zones": False,
                "work_stealing": False,
                "zipf": False,
                "real_trace": False,
            },
        }


@dataclass(frozen=True)
class StaticOwnershipThresholdResult:
    run_rows: list[dict[str, Any]]
    aggregate_rows: list[dict[str, Any]]
    partition_rows: list[dict[str, Any]]
    validation: dict[str, Any]
    findings: dict[str, Any]


def load_static_ownership_threshold_config(
    path: str | Path,
) -> StaticOwnershipThresholdConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    base_dir = repository_root_for_config(config_path)
    output_dir = Path(raw["output_dir"]).expanduser()
    if not output_dir.is_absolute():
        output_dir = (base_dir / output_dir).resolve()
    workload_raw = dict(raw["workload"])
    workload_raw["hot_owner_task_counts"] = tuple(
        int(value) for value in workload_raw["hot_owner_task_counts"]
    )
    config = StaticOwnershipThresholdConfig(
        output_dir=output_dir,
        seeds=tuple(int(value) for value in raw["seeds"]),
        geometry=PanelGeometryConfig(**raw["geometry"]),
        movement=PanelMovementConfig(**raw["movement"]),
        timing=PanelTimingConfig(**raw["timing"]),
        workload=StaticOwnershipThresholdWorkloadConfig(**workload_raw),
    )
    config.validate()
    return config


def owner_counts_for_hot_task_count(
    task_count: int,
    zone_count: int,
    hot_owner: int,
    hot_task_count: int,
) -> tuple[int, ...]:
    cold_total = task_count - hot_task_count
    cold_base, extra = divmod(cold_total, zone_count - 1)
    counts = []
    cold_index = 0
    for zone_id in range(zone_count):
        if zone_id == hot_owner:
            counts.append(hot_task_count)
            continue
        counts.append(cold_base + (1 if cold_index < extra else 0))
        cold_index += 1
    return tuple(counts)


def run_static_ownership_threshold(
    config: StaticOwnershipThresholdConfig,
) -> StaticOwnershipThresholdResult:
    config.validate()
    run_rows: list[dict[str, Any]] = []
    partition_rows: list[dict[str, Any]] = []
    failures: list[str] = []

    for seed in config.seeds:
        expected_coordinates: list[tuple[int, int]] | None = None
        expected_multiplicities: list[int] | None = None
        for hot_tasks in config.workload.hot_owner_task_counts:
            owner_counts = owner_counts_for_hot_task_count(
                config.workload.task_count,
                config.zone_count,
                config.workload.hot_owner,
                hot_tasks,
            )
            simulator = PanelStaticZoneSimulator(_panel_config(config, seed))
            targets = build_paired_unique_tasks(
                simulator,
                owner_counts,
                config.workload.task_count,
                config.workload.request_size_bytes,
                seed,
            )
            coordinates = [
                reader_relative_signature(
                    request,
                    config.geometry.slots_per_half,
                    config.geometry.zone_height_racks,
                )
                for request in targets
            ]
            if expected_coordinates is None:
                expected_coordinates = coordinates
            elif coordinates != expected_coordinates:
                failures.append(
                    f"seed {seed} hot_tasks {hot_tasks}: local coordinates changed"
                )

            logical = expand_logical_requests(
                targets,
                config.workload.logical_request_count,
                config.workload.request_size_bytes,
                seed,
            )
            merged = merge_panel_requests(logical)
            multiplicities = [
                request.merged_request_count for request in merged
            ]
            if expected_multiplicities is None:
                expected_multiplicities = multiplicities
            elif multiplicities != expected_multiplicities:
                failures.append(
                    f"seed {seed} hot_tasks {hot_tasks}: multiplicities changed"
                )
            _validate_trace(
                config,
                owner_counts,
                logical,
                merged,
                f"seed {seed} hot_tasks {hot_tasks}",
                failures,
            )

            result = simulator.run(merged)
            work = [float(row["active_cycle_s"]) for row in result.zone_rows]
            hot_share = hot_tasks / config.workload.task_count
            run_rows.append(
                {
                    "seed": seed,
                    "hot_owner_task_count": hot_tasks,
                    "hot_owner_task_share": hot_share,
                    "logical_request_count": result.summary["request_count"],
                    "physical_task_count": result.summary[
                        "service_operation_count"
                    ],
                    "owner_counts": "/".join(
                        str(value) for value in owner_counts
                    ),
                    "system_drain_s": result.summary["system_drain_s"],
                    "batch_throughput_req_per_s": (
                        result.summary["request_count"]
                        / result.summary["system_drain_s"]
                    ),
                    "capacity_efficiency": result.summary[
                        "static_capacity_efficiency"
                    ],
                    "stranded_capacity_share": result.summary[
                        "stranded_capacity_share"
                    ],
                    "stranded_shuttle_time_s": result.summary[
                        "stranded_capacity_s"
                    ],
                    "busiest_owner_work_over_mean": (
                        max(work) / mean(work)
                    ),
                    "target_busiest_owner_amplification": (
                        hot_tasks
                        / (config.workload.task_count / config.zone_count)
                    ),
                    "normalized_throughput": 0.0,
                    "throughput_loss": 0.0,
                    "shuttle_count": result.summary["shuttle_count"],
                    "reader_count": result.summary["reader_count"],
                }
            )
            for zone in result.zone_rows:
                partition_rows.append(
                    {
                        "seed": seed,
                        "hot_owner_task_count": hot_tasks,
                        "hot_owner_task_share": hot_share,
                        "partition_id": zone["zone_id"],
                        "task_count": zone["glass_service_count"],
                        "logical_request_count": zone[
                            "logical_request_count"
                        ],
                        "completion_s": zone["completion_s"],
                        "active_work_s": zone["active_cycle_s"],
                        "idle_tail_s": (
                            result.summary["system_drain_s"]
                            - zone["completion_s"]
                        ),
                    }
                )

    _normalize_throughput(config, run_rows)
    aggregate_rows = _aggregate(run_rows)
    _validate_results(config, aggregate_rows, failures)
    if failures:
        raise RuntimeError(
            "static-ownership threshold validation failed: "
            + "; ".join(failures)
        )
    findings = _build_findings(config, aggregate_rows)
    return StaticOwnershipThresholdResult(
        run_rows=run_rows,
        aggregate_rows=aggregate_rows,
        partition_rows=partition_rows,
        validation={
            "passed": True,
            "checked_runs": len(run_rows),
            "paired_seeds": len(config.seeds),
            "exact_logical_requests": config.workload.logical_request_count,
            "exact_post_merge_tasks": config.workload.task_count,
            "paired_reader_relative_coordinates": True,
            "paired_merge_multiplicities": True,
            "fixed_shuttles": config.zone_count,
            "fixed_active_readers": config.zone_count,
            "monotonic_throughput_loss": True,
            "failures": [],
        },
        findings=findings,
    )


def write_static_ownership_threshold_outputs(
    config: StaticOwnershipThresholdConfig,
    result: StaticOwnershipThresholdResult,
) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    _write_rows(config.output_dir / "run_summary.csv", result.run_rows)
    _write_rows(
        config.output_dir / "aggregate_summary.csv",
        result.aggregate_rows,
    )
    _write_rows(
        config.output_dir / "partition_summary.csv",
        result.partition_rows,
    )
    with (config.output_dir / "config.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(config.to_json_dict(), handle, indent=2)
        handle.write("\n")
    with (config.output_dir / "summary.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(
            {
                "config": config.to_json_dict(),
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
        config.output_dir / "STATIC_OWNERSHIP_THRESHOLD_ANALYSIS_ZH.md",
        config,
        result,
    )
    figures_dir = config.output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    _write_figures(config, result, figures_dir)


def _panel_config(
    config: StaticOwnershipThresholdConfig,
    seed: int,
) -> PanelStaticZoneConfig:
    return PanelStaticZoneConfig(
        output_dir=config.output_dir,
        seed=seed,
        geometry=config.geometry,
        movement=config.movement,
        timing=config.timing,
        workload=PanelWorkloadConfig(
            batch_size=config.workload.logical_request_count,
            request_size_bytes=config.workload.request_size_bytes,
            placement="uniform_round_robin",
            request_merge=True,
        ),
    )


def _validate_trace(
    config: StaticOwnershipThresholdConfig,
    owner_counts: tuple[int, ...],
    logical: list[Any],
    merged: list[Any],
    label: str,
    failures: list[str],
) -> None:
    if len(logical) != config.workload.logical_request_count:
        failures.append(f"{label}: logical request count changed")
    if len(merged) != config.workload.task_count:
        failures.append(f"{label}: merge did not retain 640 physical tasks")
    if sum(request.merged_request_count for request in merged) != len(logical):
        failures.append(f"{label}: merge lost logical requests")
    if sum(request.size_bytes for request in merged) != sum(
        request.size_bytes for request in logical
    ):
        failures.append(f"{label}: merge changed bytes")
    observed = tuple(
        sum(request.zone_id == zone_id for request in merged)
        for zone_id in range(config.zone_count)
    )
    if observed != owner_counts:
        failures.append(f"{label}: observed owner counts differ from target")
    if len({request.platter_id for request in merged}) != len(merged):
        failures.append(f"{label}: physical platter ownership overlaps")


def _normalize_throughput(
    config: StaticOwnershipThresholdConfig,
    rows: list[dict[str, Any]],
) -> None:
    balanced_count = config.workload.hot_owner_task_counts[0]
    baselines = {
        int(row["seed"]): float(row["batch_throughput_req_per_s"])
        for row in rows
        if row["hot_owner_task_count"] == balanced_count
    }
    for row in rows:
        normalized = (
            float(row["batch_throughput_req_per_s"])
            / baselines[int(row["seed"])]
        )
        row["normalized_throughput"] = normalized
        row["throughput_loss"] = 1.0 - normalized


def _aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(int(row["hot_owner_task_count"]), []).append(row)
    identity = {"seed", "hot_owner_task_count", "owner_counts"}
    aggregates = []
    for hot_tasks, group in sorted(groups.items()):
        aggregate: dict[str, Any] = {
            "hot_owner_task_count": hot_tasks,
            "owner_counts": group[0]["owner_counts"],
            "run_count": len(group),
        }
        for field in group[0]:
            if field in identity:
                continue
            values = [float(row[field]) for row in group]
            std = pstdev(values) if len(values) > 1 else 0.0
            aggregate[f"{field}_mean"] = mean(values)
            aggregate[f"{field}_std"] = std
            aggregate[f"{field}_ci95"] = (
                1.96 * std / math.sqrt(len(values))
            )
        aggregates.append(aggregate)
    return aggregates


def _validate_results(
    config: StaticOwnershipThresholdConfig,
    rows: list[dict[str, Any]],
    failures: list[str],
) -> None:
    if len(rows) != len(config.workload.hot_owner_task_counts):
        failures.append("aggregate sweep point count changed")
    throughput = [
        float(row["normalized_throughput_mean"]) for row in rows
    ]
    stranded = [
        float(row["stranded_capacity_share_mean"]) for row in rows
    ]
    if any(
        right > left + 1e-9
        for left, right in zip(throughput, throughput[1:])
    ):
        failures.append("normalized throughput is not monotonic")
    if any(
        right + 1e-9 < left
        for left, right in zip(stranded, stranded[1:])
    ):
        failures.append("stranded capacity is not monotonic")
    for row in rows:
        if (
            row["physical_task_count_mean"] != config.workload.task_count
            or row["logical_request_count_mean"]
            != config.workload.logical_request_count
        ):
            failures.append("a sweep point changed logical or physical work")
        if (
            row["shuttle_count_mean"] != config.zone_count
            or row["reader_count_mean"] != config.zone_count
        ):
            failures.append("a sweep point changed hardware resources")


def _build_findings(
    config: StaticOwnershipThresholdConfig,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    crossings = {}
    for loss in (0.10, 0.20, 0.30, 0.50):
        row = next(
            (
                candidate
                for candidate in rows
                if candidate["throughput_loss_mean"] >= loss
            ),
            None,
        )
        crossings[f"{int(loss * 100)}_percent_loss"] = (
            {
                "hot_owner_task_count": row["hot_owner_task_count"],
                "hot_owner_task_share": row[
                    "hot_owner_task_share_mean"
                ],
                "normalized_throughput": row[
                    "normalized_throughput_mean"
                ],
                "throughput_loss": row["throughput_loss_mean"],
                "capacity_efficiency": row[
                    "capacity_efficiency_mean"
                ],
                "stranded_capacity_share": row[
                    "stranded_capacity_share_mean"
                ],
            }
            if row
            else None
        )
    knee = _skew_impact_knee(rows)
    return {
        "crossings": crossings,
        "skew_impact_knee": {
            **_finding_row(knee),
            "hot_owner_task_count": knee["hot_owner_task_count"],
            "selection_score": knee["skew_impact_score"],
            "selection_method": (
                "Maximum normalized throughput-loss gain over normalized "
                "owner-share increase across the tested sweep."
            ),
        },
        "balanced": _finding_row(rows[0]),
        "moderate_25_percent": _finding_row(
            next(
                row
                for row in rows
                if row["hot_owner_task_count"]
                == config.workload.task_count // 4
            )
        ),
        "strong_50_percent": _finding_row(rows[-1]),
        "interpretation": (
            "No natural discontinuity is assumed. Crossings are observed "
            "engineering thresholds relative to the paired balanced case."
        ),
    }


def _skew_impact_knee(rows: list[dict[str, Any]]) -> dict[str, Any]:
    first = rows[0]
    last = rows[-1]
    x_min = float(first["hot_owner_task_share_mean"])
    x_span = float(last["hot_owner_task_share_mean"]) - x_min
    loss_min = float(first["throughput_loss_mean"])
    loss_span = float(last["throughput_loss_mean"]) - loss_min
    if x_span <= 0 or loss_span <= 0:
        return dict(first) | {"skew_impact_score": 0.0}

    scored = []
    for row in rows:
        normalized_skew = (
            float(row["hot_owner_task_share_mean"]) - x_min
        ) / x_span
        normalized_loss = (
            float(row["throughput_loss_mean"]) - loss_min
        ) / loss_span
        scored.append(
            dict(row)
            | {
                "skew_impact_score": normalized_loss - normalized_skew,
            }
        )
    return max(scored, key=lambda row: row["skew_impact_score"])


def _finding_row(row: dict[str, Any]) -> dict[str, float]:
    return {
        "hot_owner_task_share": row["hot_owner_task_share_mean"],
        "normalized_throughput": row["normalized_throughput_mean"],
        "throughput_loss": row["throughput_loss_mean"],
        "capacity_efficiency": row["capacity_efficiency_mean"],
        "stranded_capacity_share": row[
            "stranded_capacity_share_mean"
        ],
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


def _write_report(
    path: Path,
    config: StaticOwnershipThresholdConfig,
    result: StaticOwnershipThresholdResult,
) -> None:
    crossings = result.findings["crossings"]
    knee = result.findings["skew_impact_knee"]
    lines = [
        "# Static Ownership Throughput Threshold",
        "",
        "## 問題",
        "",
        "當最忙 partition 擁有越來越多 post-merge physical tasks 時，"
        "static ownership 從什麼程度開始造成明顯 throughput loss？",
        "",
        "## 控制條件",
        "",
        f"- 固定 {config.zone_count} 個 static non-overlapping partitions、"
        f"{config.zone_count} 個 shuttles 與 {config.zone_count} 個 readers。",
        f"- 每個 batch 固定 {config.workload.logical_request_count:,} 個 "
        f"{config.workload.request_size_bytes / MIB:.0f} MiB requests。",
        f"- Batch-wide merge 後固定為 {config.workload.task_count} 個 tasks。",
        f"- 共 {len(config.workload.hot_owner_task_counts)} 個 concentration points，"
        f"每點使用 {len(config.seeds)} 個 paired seeds。",
        "- 所有 points 使用相同 reader-relative coordinates 與 merge multiplicities。",
        "- 不包含 Adaptive、work stealing、Zipf 或真實 trace。",
        "",
        "## Throughput loss crossings",
        "",
    ]
    for loss in (10, 20, 30, 50):
        crossing = crossings[f"{loss}_percent_loss"]
        if crossing is None:
            lines.append(f"- {loss}% loss：本次 sweep 未達到。")
            continue
        lines.append(
            f"- {loss}% loss：最早出現在 hot-owner share "
            f"{crossing['hot_owner_task_share'] * 100:.2f}%；"
            f"實測 throughput loss 為 "
            f"{crossing['throughput_loss'] * 100:.1f}%，"
            f"stranded capacity 為 "
            f"{crossing['stranded_capacity_share'] * 100:.1f}%。"
        )
    moderate = result.findings["moderate_25_percent"]
    strong = result.findings["strong_50_percent"]
    lines.extend(
        [
            "",
            "## Skew-impact knee",
            "",
            f"- 最大 normalized loss-over-skew gap 出現在 "
            f"{knee['hot_owner_task_share'] * 100:.2f}% owner share。",
            f"- 此時 throughput loss 為 {knee['throughput_loss'] * 100:.1f}%，"
            f"stranded capacity 為 {knee['stranded_capacity_share'] * 100:.1f}%。",
            "- 這是 sweep 內兼顧較低 skew 與較高 throughput loss 的代表點，"
            "不是系統的物理臨界點。",
            "",
            "## 代表結果",
            "",
            f"- 25% hot-owner share：保留 "
            f"{moderate['normalized_throughput'] * 100:.1f}% throughput，"
            f"損失 {moderate['throughput_loss'] * 100:.1f}%。",
            f"- 50% hot-owner share：保留 "
            f"{strong['normalized_throughput'] * 100:.1f}% throughput，"
            f"損失 {strong['throughput_loss'] * 100:.1f}%。",
            "",
            "## 解讀",
            "",
            "本實驗不預設存在突然的物理斷層。圖中的 crossing 是相對 balanced "
            "case 的工程門檻。若曲線平滑下降，正確結論是 static ownership "
            "在偏離均衡後便持續損失 throughput，而不是宣稱存在神奇臨界點。",
            "",
            "## Figure guide",
            "",
            "- `fig1_throughput_vs_owner_concentration`：單一 throughput 主線與 skew-impact knee。",
            "- `fig2_why_throughput_drops`：同一 knee workload 的八個 shuttle working/idle timeline。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_figures(
    config: StaticOwnershipThresholdConfig,
    result: StaticOwnershipThresholdResult,
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
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )
    rows = result.aggregate_rows
    x = [row["hot_owner_task_share_mean"] * 100 for row in rows]
    retained = [row["normalized_throughput_mean"] * 100 for row in rows]
    knee = result.findings["skew_impact_knee"]

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.plot(
        x,
        retained,
        color="#2F6B9A",
        marker="o",
        markersize=4.5,
        linewidth=2.2,
    )
    knee_x = knee["hot_owner_task_share"] * 100
    knee_y = knee["normalized_throughput"] * 100
    ax.scatter(
        [knee_x],
        [knee_y],
        s=70,
        color="#C44E52",
        edgecolor="white",
        linewidth=1.2,
        zorder=4,
    )
    ax.annotate(
        f"Skew-impact knee\n{knee_x:.2f}% share, "
        f"{knee['throughput_loss'] * 100:.1f}% loss",
        xy=(knee_x, knee_y),
        xytext=(knee_x + 5.0, knee_y + 10),
        arrowprops={"arrowstyle": "-", "color": "#626870"},
        color="#30343B",
    )
    ax.set_xlabel("Post-merge tasks at busiest owner (%)")
    ax.set_ylabel("Throughput retained vs. balanced (%)")
    ax.set_title("A modest ownership skew causes disproportionate throughput loss")
    ax.set_xlim(min(x) - 1, max(x) + 1)
    ax.set_ylim(20, 104)
    ax.grid(axis="y", alpha=0.22)
    fig.tight_layout()
    _save(fig, figures_dir, "fig1_throughput_vs_owner_concentration")

    crossing_hot_tasks = int(knee["hot_owner_task_count"])
    representative = [
        row
        for row in result.partition_rows
        if row["seed"] == config.seeds[0]
        and row["hot_owner_task_count"] == crossing_hot_tasks
    ]
    representative.sort(key=lambda row: row["partition_id"])
    drain = max(float(row["completion_s"]) for row in representative)
    y = list(range(config.zone_count))
    active = [float(row["completion_s"]) / 3600 for row in representative]
    idle = [
        (drain - float(row["completion_s"])) / 3600
        for row in representative
    ]
    colors = [
        "#C44E52"
        if int(row["partition_id"]) == config.workload.hot_owner
        else "#4C9F70"
        for row in representative
    ]
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.barh(y, active, color=colors)
    ax.barh(y, idle, left=active, color="#D9DEE5")
    ax.set_yticks(y, [f"P{index}" for index in y])
    ax.invert_yaxis()
    ax.set_xlabel("Batch drain time (hours)")
    ax.set_title(
        f"At {crossing_hot_tasks / config.workload.task_count * 100:.2f}% "
        "owner share, cold shuttles finish early"
    )
    ax.grid(axis="x", alpha=0.22)
    ax.legend(
        handles=[
            Patch(color="#C44E52", label="Busiest owner"),
            Patch(color="#4C9F70", label="Other owners"),
            Patch(color="#D9DEE5", label="Idle while batch waits"),
        ],
        frameon=False,
        loc="lower right",
    )
    fig.tight_layout()
    _save(fig, figures_dir, "fig2_why_throughput_drops")


def _save(fig: Any, figures_dir: Path, stem: str) -> None:
    fig.savefig(figures_dir / f"{stem}.png", dpi=220, bbox_inches="tight")
    fig.savefig(figures_dir / f"{stem}.pdf", bbox_inches="tight")
    import matplotlib.pyplot as plt

    plt.close(fig)
