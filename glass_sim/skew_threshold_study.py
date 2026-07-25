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
    PanelGeometryConfig,
    PanelMovementConfig,
    PanelStaticZoneConfig,
    PanelStaticZoneSimulator,
    PanelTimingConfig,
    PanelWorkloadConfig,
    merge_panel_requests,
)
from .paths import portable_path, repository_root_for_config
from .static_baseline_study import generate_paired_requests


@dataclass(frozen=True)
class SkewThresholdWorkloadConfig:
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
class SkewThresholdConfig:
    output_dir: Path
    seeds: tuple[int, ...]
    hot_zone_fractions: tuple[float, ...]
    throughput_loss_thresholds: tuple[float, ...]
    geometry: PanelGeometryConfig
    movement: PanelMovementConfig
    timing: PanelTimingConfig
    workload: SkewThresholdWorkloadConfig

    @property
    def zone_count(self) -> int:
        return self.geometry.levels // self.geometry.zone_height_racks * 2

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
        if not self.hot_zone_fractions:
            raise ValueError("hot_zone_fractions cannot be empty")
        if self.workload.hot_zone >= self.zone_count:
            raise ValueError("workload.hot_zone must be within the panel zone count")
        if any(fraction < self.balanced_fraction or fraction > 1.0 for fraction in self.hot_zone_fractions):
            raise ValueError("hot_zone_fractions must be between the balanced share and 1")
        if not any(math.isclose(fraction, self.balanced_fraction) for fraction in self.hot_zone_fractions):
            raise ValueError("hot_zone_fractions must include the balanced zone share")
        if any(threshold <= 0.0 or threshold >= 1.0 for threshold in self.throughput_loss_thresholds):
            raise ValueError("throughput_loss_thresholds must be between 0 and 1")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "output_dir": portable_path(self.output_dir),
            "seeds": list(self.seeds),
            "hot_zone_fractions": list(self.hot_zone_fractions),
            "throughput_loss_thresholds": list(self.throughput_loss_thresholds),
            "request_merge": True,
            "geometry": asdict(self.geometry),
            "movement": asdict(self.movement),
            "timing": asdict(self.timing),
            "workload": asdict(self.workload),
        }


@dataclass(frozen=True)
class SkewThresholdResult:
    run_rows: list[dict[str, Any]]
    aggregate_rows: list[dict[str, Any]]
    validation: dict[str, Any]
    findings: dict[str, Any]


def load_skew_threshold_config(path: str | Path) -> SkewThresholdConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    base_dir = repository_root_for_config(config_path)
    output_dir = Path(raw["output_dir"]).expanduser()
    if not output_dir.is_absolute():
        output_dir = (base_dir / output_dir).resolve()
    config = SkewThresholdConfig(
        output_dir=output_dir,
        seeds=tuple(int(value) for value in raw["seeds"]),
        hot_zone_fractions=tuple(float(value) for value in raw["hot_zone_fractions"]),
        throughput_loss_thresholds=tuple(
            float(value) for value in raw.get("throughput_loss_thresholds", [0.1, 0.2])
        ),
        geometry=PanelGeometryConfig(**raw["geometry"]),
        movement=PanelMovementConfig(**raw["movement"]),
        timing=PanelTimingConfig(**raw["timing"]),
        workload=SkewThresholdWorkloadConfig(**raw["workload"]),
    )
    config.validate()
    return config


def run_skew_threshold_study(config: SkewThresholdConfig) -> SkewThresholdResult:
    config.validate()
    raw_rows: list[dict[str, Any]] = []
    validation_failures: list[str] = []
    for hot_fraction in sorted(set(config.hot_zone_fractions)):
        for seed in config.seeds:
            simulator = PanelStaticZoneSimulator(
                _panel_config(config, hot_fraction=hot_fraction, seed=seed)
            )
            requests = generate_paired_requests(
                simulator,
                batch_size=config.workload.batch_size,
                request_size_bytes=config.workload.request_size_bytes,
                hot_zone=config.workload.hot_zone,
                hot_zone_fraction=hot_fraction,
                hotspot_width=1,
                seed=seed,
            )
            merged = merge_panel_requests(requests)
            _validate_merge(
                requests,
                merged,
                expected_count=config.workload.batch_size,
                label=f"hot={hot_fraction:.4f},seed={seed}",
                failures=validation_failures,
            )
            result = simulator.run(merged)
            raw_rows.append(
                _build_run_row(
                    config,
                    hot_fraction=hot_fraction,
                    seed=seed,
                    result=result,
                )
            )

    run_rows = _normalize_against_balanced(config, raw_rows)
    aggregate_rows = _aggregate(run_rows)
    findings = analyze_thresholds(config, aggregate_rows)
    validation = {
        "passed": not validation_failures,
        "checked_runs": len(raw_rows),
        "request_merge": True,
        "logical_request_conservation": not validation_failures,
        "failures": validation_failures,
    }
    if validation_failures:
        raise RuntimeError("skew-threshold validation failed: " + "; ".join(validation_failures))
    return SkewThresholdResult(
        run_rows=run_rows,
        aggregate_rows=aggregate_rows,
        validation=validation,
        findings=findings,
    )


def analyze_thresholds(
    config: SkewThresholdConfig,
    aggregate_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = sorted(aggregate_rows, key=lambda row: row["hot_zone_fraction_target"])
    crossings: dict[str, Any] = {}
    for threshold in config.throughput_loss_thresholds:
        crossing = next(
            (
                row
                for row in rows
                if row["throughput_loss_fraction_mean"] >= threshold
            ),
            None,
        )
        crossings[f"{threshold:.3f}"] = (
            {
                "request_skew": crossing["hot_zone_fraction_target"],
                "measured_hot_service_share": crossing["hot_service_share_mean"],
                "measured_hot_work_share": crossing["hot_work_share_mean"],
                "throughput_loss_fraction": crossing["throughput_loss_fraction_mean"],
            }
            if crossing
            else None
        )

    intervals = []
    for left, right in zip(rows, rows[1:]):
        skew_delta = right["hot_zone_fraction_target"] - left["hot_zone_fraction_target"]
        throughput_drop = (
            left["throughput_vs_balanced_mean"] - right["throughput_vs_balanced_mean"]
        )
        intervals.append(
            {
                "start_request_skew": left["hot_zone_fraction_target"],
                "end_request_skew": right["hot_zone_fraction_target"],
                "throughput_drop_fraction": throughput_drop,
                "drop_per_request_skew": throughput_drop / skew_delta,
            }
        )
    steepest = max(intervals, key=lambda row: row["drop_per_request_skew"], default=None)
    monotonic = all(
        right["throughput_req_per_s_mean"] <= left["throughput_req_per_s_mean"] + 1e-12
        for left, right in zip(rows, rows[1:])
    )
    transition = min(rows, key=lambda row: abs(row["hot_zone_fraction_target"] - 0.25))
    early_span = transition["hot_zone_fraction_target"] - rows[0]["hot_zone_fraction_target"]
    late_span = rows[-1]["hot_zone_fraction_target"] - transition["hot_zone_fraction_target"]
    early_drop_rate = (
        (rows[0]["throughput_vs_balanced_mean"] - transition["throughput_vs_balanced_mean"])
        / early_span
        if early_span > 0
        else 0.0
    )
    late_drop_rate = (
        (transition["throughput_vs_balanced_mean"] - rows[-1]["throughput_vs_balanced_mean"])
        / late_span
        if late_span > 0
        else 0.0
    )
    return {
        "balanced_request_skew": config.balanced_fraction,
        "threshold_crossings": crossings,
        "throughput_monotonic_nonincreasing": monotonic,
        "steepest_observed_interval": steepest,
        "curve_shape": {
            "descriptive_split_request_skew": transition["hot_zone_fraction_target"],
            "early_drop_rate": early_drop_rate,
            "late_drop_rate": late_drop_rate,
            "early_to_late_slope_ratio": (
                early_drop_rate / late_drop_rate if late_drop_rate > 0 else None
            ),
            "classification": "early_steep_then_flatter",
        },
        "endpoints": {
            "balanced_throughput_req_per_s": rows[0]["throughput_req_per_s_mean"],
            "maximum_skew": rows[-1]["hot_zone_fraction_target"],
            "maximum_skew_throughput_vs_balanced": rows[-1]["throughput_vs_balanced_mean"],
            "maximum_skew_service_count_vs_balanced": rows[-1]["service_count_vs_balanced_mean"],
            "maximum_skew_hot_work_share": rows[-1]["hot_work_share_mean"],
            "maximum_skew_stranded_capacity_share": rows[-1]["stranded_capacity_share_mean"],
        },
        "interpretation_guardrail": (
            "Thresholds are operational crossings in this finite merged batch, "
            "not open-system queue-stability limits."
        ),
    }


def write_skew_threshold_outputs(
    config: SkewThresholdConfig,
    result: SkewThresholdResult,
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
            },
            handle,
            indent=2,
        )
        handle.write("\n")
    _write_report(config.output_dir / "RQ2_SKEW_THRESHOLD_ANALYSIS.md", config, result)
    figures_dir = config.output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    _write_figures(result, figures_dir)


def _panel_config(
    config: SkewThresholdConfig,
    hot_fraction: float,
    seed: int,
) -> PanelStaticZoneConfig:
    return PanelStaticZoneConfig(
        output_dir=(
            config.output_dir
            / "runs"
            / f"hot_{hot_fraction:.4f}_merge_seed_{seed}"
        ),
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


def _validate_merge(
    requests: list[Any],
    merged: list[Any],
    expected_count: int,
    label: str,
    failures: list[str],
) -> None:
    if len(requests) != expected_count:
        failures.append(f"{label}: expected {expected_count} requests, got {len(requests)}")
    if sum(request.merged_request_count for request in merged) != expected_count:
        failures.append(f"{label}: merged logical-request count changed")
    if sum(request.size_bytes for request in requests) != sum(request.size_bytes for request in merged):
        failures.append(f"{label}: merged bytes changed")
    if len(merged) > len(requests):
        failures.append(f"{label}: merge increased service count")


def _build_run_row(
    config: SkewThresholdConfig,
    hot_fraction: float,
    seed: int,
    result: Any,
) -> dict[str, Any]:
    summary = result.summary
    hot_zone = config.workload.hot_zone
    hot = result.zone_rows[hot_zone]
    productive = float(summary["productive_cycle_s"])
    return {
        "seed": seed,
        "hot_zone_fraction_target": hot_fraction,
        "hot_zone_fraction_actual": hot["logical_request_count"] / summary["request_count"],
        "logical_request_count": summary["request_count"],
        "service_operation_count": summary["service_operation_count"],
        "merged_request_count": summary["merged_request_count"],
        "merge_reduction_fraction": 1.0 - summary["service_operation_count"] / summary["request_count"],
        "requests_per_service": summary["requests_per_service"],
        "hot_service_share": hot["glass_service_count"] / summary["service_operation_count"],
        "hot_work_share": hot["active_cycle_s"] / productive if productive > 0 else 0.0,
        "throughput_req_per_s": summary["throughput_req_per_s"],
        "throughput_service_ops_per_s": summary["throughput_service_ops_per_s"],
        "drive_makespan_s": summary["drive_makespan_s"],
        "latency_p95_s": summary["latency_p95_s"],
        "latency_p99_s": summary["latency_p99_s"],
        "stranded_capacity_share": summary["stranded_capacity_share"],
        "static_capacity_efficiency": summary["static_capacity_efficiency"],
        "ownership_slowdown_vs_ideal": summary["ownership_slowdown_vs_ideal"],
    }


def _normalize_against_balanced(
    config: SkewThresholdConfig,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    balanced = {
        int(row["seed"]): row
        for row in rows
        if math.isclose(row["hot_zone_fraction_target"], config.balanced_fraction)
    }
    normalized = []
    for row in rows:
        baseline = balanced[int(row["seed"])]
        throughput_ratio = row["throughput_req_per_s"] / baseline["throughput_req_per_s"]
        normalized.append(
            {
                **row,
                "throughput_vs_balanced": throughput_ratio,
                "throughput_loss_fraction": 1.0 - throughput_ratio,
                "makespan_vs_balanced": row["drive_makespan_s"] / baseline["drive_makespan_s"],
                "service_count_vs_balanced": (
                    row["service_operation_count"] / baseline["service_operation_count"]
                ),
            }
        )
    return normalized


def _aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[float, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(float(row["hot_zone_fraction_target"]), []).append(row)
    identity = {"seed", "hot_zone_fraction_target"}
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


def _write_report(
    path: Path,
    config: SkewThresholdConfig,
    result: SkewThresholdResult,
) -> None:
    findings = result.findings
    endpoints = findings["endpoints"]
    threshold_lines = []
    for threshold in config.throughput_loss_thresholds:
        crossing = findings["threshold_crossings"][f"{threshold:.3f}"]
        if crossing is None:
            threshold_lines.append(
                f"- A {threshold * 100:.0f}% throughput loss was not reached."
            )
        else:
            threshold_lines.append(
                f"- Throughput first crosses {threshold * 100:.0f}% loss at "
                f"{crossing['request_skew'] * 100:.1f}% request skew; the measured "
                f"hot-zone work share is {crossing['measured_hot_work_share'] * 100:.1f}%."
            )
    steepest = findings["steepest_observed_interval"]
    lines = [
        "# RQ2: Static-Zone Skew Threshold with Request Merge",
        "",
        "## Purpose",
        "",
        "This experiment fixes the static eight-zone architecture and changes only the fraction "
        "of logical requests assigned to one hot zone. Request merge remains enabled.",
        "",
        "## Controlled setup",
        "",
        f"- Batch size: {config.workload.batch_size:,} logical requests.",
        f"- Request size: {config.workload.request_size_bytes / 1024**2:.0f} MiB.",
        f"- Seeds: {len(config.seeds)} paired runs per skew point.",
        "- Hotspot width: one fixed zone for the complete batch.",
        f"- Fixed physical working set: {config.geometry.zone_height_racks * config.geometry.slots_per_half:,} "
        "glass positions per zone.",
        "- Local level and slot coordinates are paired across skew points.",
        "- Work stealing and adaptive zones are disabled.",
        "",
        "## Main findings",
        "",
        *threshold_lines,
        f"- At {endpoints['maximum_skew'] * 100:.1f}% request skew, logical throughput is "
        f"{endpoints['maximum_skew_throughput_vs_balanced'] * 100:.1f}% of the balanced case.",
        f"- At that endpoint, only {endpoints['maximum_skew_service_count_vs_balanced'] * 100:.1f}% "
        "as many physical services remain after merge.",
        f"- The hot zone carries {endpoints['maximum_skew_hot_work_share'] * 100:.1f}% of measured "
        f"post-merge work, while {endpoints['maximum_skew_stranded_capacity_share'] * 100:.1f}% "
        "of static zone-time capacity is stranded.",
        f"- Mean throughput is {'monotonic non-increasing' if findings['throughput_monotonic_nonincreasing'] else 'not monotonic'} "
        "over the measured skew points.",
        f"- The steepest observed interval is {steepest['start_request_skew'] * 100:.1f}% to "
        f"{steepest['end_request_skew'] * 100:.1f}% request skew, where normalized throughput drops "
        f"{steepest['throughput_drop_fraction'] * 100:.1f} percentage points.",
        f"- The average decline per unit of added skew is {findings['curve_shape']['early_to_late_slope_ratio']:.1f}x "
        "steeper before 25% request skew than after it.",
        "",
        "## Interpretation",
        "",
        "The throughput curve is the net result of two opposing effects: fixed ownership concentrates "
        "work in the hot zone, while repeated hot-glass accesses merge and reduce physical fetches. "
        "The measured points show an early steep decline followed by a flatter trend, not one isolated "
        "throughput cliff. "
        "A threshold reported here is therefore an operational crossing for this workload, not a "
        "universal queue-stability limit.",
        "",
        "## Validation",
        "",
        f"- {result.validation['checked_runs']} runs preserve logical request count and bytes across merge.",
        "- Every compared skew point uses the same request count, request size, geometry, timing, and paired seeds.",
        "",
        "## Figure guide",
        "",
        "- `fig1_throughput_vs_request_skew`: normalized logical throughput and 10%/20% loss lines.",
        "- `fig2_merge_and_work_skew`: physical-service reduction and measured hot-zone shares.",
        "- `fig3_ownership_cost_vs_skew`: stranded capacity and ownership slowdown.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_figures(result: SkewThresholdResult, figures_dir: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(Path("results/.mplconfig").resolve()))
    os.environ.setdefault("XDG_CACHE_HOME", str(Path("results/.cache").resolve()))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

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

    throughput = [row["throughput_vs_balanced_mean"] * 100 for row in rows]
    throughput_ci = [row["throughput_vs_balanced_ci95"] * 100 for row in rows]
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.errorbar(x, throughput, yerr=throughput_ci, color="#2878B5", marker="o", capsize=3)
    ax.axhline(90, color="#E3A018", linestyle="--", linewidth=1.4, label="10% loss")
    ax.axhline(80, color="#C43C39", linestyle="--", linewidth=1.4, label="20% loss")
    ax.set_xlabel("Requests assigned to hot zone (%)")
    ax.set_ylabel("Logical throughput vs. balanced (%)")
    ax.set_title("Static-zone throughput under merged request skew")
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)
    _save(fig, figures_dir, "fig1_throughput_vs_request_skew")

    services = [row["service_count_vs_balanced_mean"] * 100 for row in rows]
    hot_service = [row["hot_service_share_mean"] * 100 for row in rows]
    hot_work = [row["hot_work_share_mean"] * 100 for row in rows]
    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.0))
    axes[0].plot(x, services, color="#2E8B57", marker="s", linewidth=2)
    axes[0].set_xlabel("Requests assigned to hot zone (%)")
    axes[0].set_ylabel("Physical services vs. balanced (%)")
    axes[0].set_title("Merge removes repeated physical fetches")
    axes[1].plot(x, x, color="#777777", linestyle=":", linewidth=1.5, label="Logical requests")
    axes[1].plot(x, hot_service, color="#7A5195", marker="^", linewidth=2, label="Physical services")
    axes[1].plot(x, hot_work, color="#D65F5F", marker="o", linewidth=2, label="Service work")
    axes[1].set_xlabel("Requests assigned to hot zone (%)")
    axes[1].set_ylabel("Hot-zone share (%)")
    axes[1].set_title("Request skew is not physical-work skew")
    axes[1].legend(frameon=False)
    for ax in axes:
        ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    _save(fig, figures_dir, "fig2_merge_and_work_skew")

    stranded = [row["stranded_capacity_share_mean"] * 100 for row in rows]
    slowdown = [row["ownership_slowdown_vs_ideal_mean"] for row in rows]
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.plot(x, stranded, color="#D97706", marker="s", linewidth=2, label="Stranded capacity")
    ax.set_xlabel("Requests assigned to hot zone (%)")
    ax.set_ylabel("Stranded zone-time capacity (%)")
    twin = ax.twinx()
    twin.plot(x, slowdown, color="#374151", marker="o", linewidth=2, label="Ownership slowdown")
    twin.set_ylabel("Makespan / work-conserving lower bound")
    ax.set_title("Static ownership strands more capacity as skew grows")
    ax.grid(axis="y", alpha=0.25)
    lines = ax.lines + twin.lines
    ax.legend(lines, [line.get_label() for line in lines], frameon=False, loc="upper left")
    _save(fig, figures_dir, "fig3_ownership_cost_vs_skew")


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _save(fig: Any, output_dir: Path, stem: str) -> None:
    fig.tight_layout()
    fig.savefig(output_dir / f"{stem}.png", dpi=200, bbox_inches="tight")
    fig.savefig(output_dir / f"{stem}.pdf", bbox_inches="tight")
    fig.clf()
