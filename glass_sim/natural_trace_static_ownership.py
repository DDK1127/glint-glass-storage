from __future__ import annotations

from dataclasses import dataclass
import csv
import json
import math
import os
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Iterable

from .natural_trace_skew import (
    MappedNaturalRequest,
    NaturalTraceSkewConfig,
    count_windows,
    load_natural_trace_skew_config,
    load_sorted_read_requests,
    map_trace_requests,
    time_windows,
    trace_request_signature,
)
from .panel_static_zone import (
    PanelStaticZoneConfig,
    PanelStaticZoneSimulator,
    PanelWorkloadConfig,
    merge_panel_requests,
)
from .paths import portable_path, repository_root_for_config


@dataclass(frozen=True)
class NaturalTraceStaticOwnershipConfig:
    output_dir: Path
    natural_trace_config_path: Path
    max_read_requests: int | None
    request_count_windows: tuple[int, ...]
    time_windows_s: tuple[float, ...]
    include_full_trace: bool
    natural_config: NaturalTraceSkewConfig

    def validate(self) -> None:
        self.natural_config.validate()
        if self.max_read_requests is not None and self.max_read_requests <= 0:
            raise ValueError("max_read_requests must be positive or null")
        if not self.request_count_windows or any(
            value <= 0 for value in self.request_count_windows
        ):
            raise ValueError("request_count_windows must contain positive values")
        if not self.time_windows_s or any(value <= 0 for value in self.time_windows_s):
            raise ValueError("time_windows_s must contain positive values")
        if len(set(self.request_count_windows)) != len(self.request_count_windows):
            raise ValueError("request_count_windows cannot contain duplicates")
        if len(set(self.time_windows_s)) != len(self.time_windows_s):
            raise ValueError("time_windows_s cannot contain duplicates")

    @property
    def zone_count(self) -> int:
        return self.natural_config.zone_count

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "output_dir": portable_path(self.output_dir),
            "natural_trace_config": portable_path(self.natural_trace_config_path),
            "max_read_requests": self.max_read_requests,
            "request_count_windows": list(self.request_count_windows),
            "time_windows_s": list(self.time_windows_s),
            "include_full_trace": self.include_full_trace,
            "balanced_reference": {
                "type": "perfect_work_balance_lower_bound",
                "definition": (
                    "The same exact productive cycle time divided evenly across "
                    "all eight owners."
                ),
                "physically_realizable_policy": False,
            },
        }


@dataclass(frozen=True)
class NaturalTraceStaticOwnershipResult:
    source: dict[str, Any]
    window_rows: list[dict[str, Any]]
    placement_rows: list[dict[str, Any]]
    family_rows: list[dict[str, Any]]
    validation: dict[str, Any]
    findings: dict[str, Any]


def load_natural_trace_static_ownership_config(
    path: str | Path,
) -> NaturalTraceStaticOwnershipConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    root = repository_root_for_config(config_path)
    natural_path = _resolve_path(raw["natural_trace_config"], root)
    config = NaturalTraceStaticOwnershipConfig(
        output_dir=_resolve_path(raw["output_dir"], root),
        natural_trace_config_path=natural_path,
        max_read_requests=(
            int(raw["max_read_requests"])
            if raw.get("max_read_requests") is not None
            else None
        ),
        request_count_windows=tuple(
            int(value) for value in raw["request_count_windows"]
        ),
        time_windows_s=tuple(float(value) for value in raw["time_windows_s"]),
        include_full_trace=bool(raw.get("include_full_trace", True)),
        natural_config=load_natural_trace_skew_config(natural_path),
    )
    config.validate()
    return config


def run_natural_trace_static_ownership(
    config: NaturalTraceStaticOwnershipConfig,
) -> NaturalTraceStaticOwnershipResult:
    config.validate()
    natural = config.natural_config
    requests, load_stats = load_sorted_read_requests(
        natural.trace_path,
        config.max_read_requests,
    )
    min_stripe = min(request.offset // natural.stripe_bytes for request in requests)
    max_stripe = max(request.offset // natural.stripe_bytes for request in requests)
    source = {
        **load_stats,
        "trace_path": portable_path(natural.trace_path),
        "trace_bytes": sum(request.size_bytes for request in requests),
        "request_signature_sha256": trace_request_signature(requests),
        "placement_count": len(natural.placements),
        "zone_count": config.zone_count,
        "balanced_owner_share": 1 / config.zone_count,
        "batch_replay_arrival_s": 0.0,
    }

    rows: list[dict[str, Any]] = []
    for placement in natural.placements:
        mapped = map_trace_requests(
            natural,
            requests,
            placement,
            min_stripe,
            max_stripe,
        )
        for window_size in config.request_count_windows:
            for window_index, window in count_windows(mapped, window_size):
                rows.append(
                    simulate_static_window(
                        config,
                        placement.name,
                        placement.display_name,
                        placement.family,
                        "request_count",
                        float(window_size),
                        window_index,
                        window,
                        is_residual=len(window) < window_size,
                    )
                )
        for window_s in config.time_windows_s:
            for window_index, window in time_windows(mapped, window_s):
                rows.append(
                    simulate_static_window(
                        config,
                        placement.name,
                        placement.display_name,
                        placement.family,
                        "time",
                        window_s,
                        window_index,
                        window,
                        is_residual=False,
                    )
                )
        if config.include_full_trace:
            rows.append(
                simulate_static_window(
                    config,
                    placement.name,
                    placement.display_name,
                    placement.family,
                    "full_trace",
                    float(len(mapped)),
                    0,
                    mapped,
                    is_residual=False,
                )
            )

    placement_rows = aggregate_placement_rows(rows)
    family_rows = aggregate_family_rows(placement_rows)
    validation = validate_results(config, source, rows)
    if not validation["passed"]:
        raise RuntimeError(
            "natural-trace static-ownership validation failed: "
            + "; ".join(validation["failures"])
        )
    findings = build_findings(config, family_rows)
    return NaturalTraceStaticOwnershipResult(
        source=source,
        window_rows=rows,
        placement_rows=placement_rows,
        family_rows=family_rows,
        validation=validation,
        findings=findings,
    )


def simulate_static_window(
    config: NaturalTraceStaticOwnershipConfig,
    placement_name: str,
    placement_display_name: str,
    placement_family: str,
    window_kind: str,
    window_size: float,
    window_index: int,
    requests: list[MappedNaturalRequest],
    is_residual: bool,
) -> dict[str, Any]:
    simulator = PanelStaticZoneSimulator(
        _panel_config(config.natural_config, max(1, len(requests)))
    )
    logical = [
        simulator.make_request(
            request_index=request.source_index,
            zone_id=request.zone_id,
            local_level=request.local_level,
            slot_in_half=request.slot_in_half,
            size_bytes=request.size_bytes,
            arrival_s=0.0,
        )
        for request in requests
    ]
    merged = merge_panel_requests(logical)
    exact = simulator.run(merged)
    active_by_zone = [0.0] * config.zone_count
    tasks_by_zone = [0] * config.zone_count
    logical_by_zone = [0] * config.zone_count
    for detail in exact.details:
        active_by_zone[detail.zone_id] += detail.cycle_s
        tasks_by_zone[detail.zone_id] += 1
        logical_by_zone[detail.zone_id] += detail.merged_request_count

    logical_count = len(requests)
    physical_count = len(merged)
    active_total = float(exact.summary["productive_cycle_s"])
    static_drain = float(exact.summary["system_drain_s"])
    ideal_drain = active_total / config.zone_count if active_total else 0.0
    static_throughput = logical_count / static_drain if static_drain else 0.0
    ideal_throughput = logical_count / ideal_drain if ideal_drain else 0.0
    retained = (
        static_throughput / ideal_throughput if ideal_throughput else 1.0
    )
    total_bytes = sum(request.size_bytes for request in requests)
    return {
        "placement": placement_name,
        "placement_display_name": placement_display_name,
        "placement_family": placement_family,
        "window_kind": window_kind,
        "window_size": window_size,
        "window_index": window_index,
        "is_residual": is_residual,
        "logical_request_count": logical_count,
        "logical_bytes": total_bytes,
        "physical_task_count": physical_count,
        "requests_per_physical_task": (
            logical_count / physical_count if physical_count else 0.0
        ),
        "busiest_logical_owner_share": (
            max(logical_by_zone) / logical_count if logical_count else 0.0
        ),
        "busiest_task_owner_share": (
            max(tasks_by_zone) / physical_count if physical_count else 0.0
        ),
        "busiest_work_owner_share": (
            max(active_by_zone) / active_total if active_total else 0.0
        ),
        "work_max_mean_ratio": (
            max(active_by_zone) / ideal_drain if ideal_drain else 1.0
        ),
        "static_drain_s": static_drain,
        "ideal_balanced_drain_s": ideal_drain,
        "static_throughput_req_per_s": static_throughput,
        "ideal_balanced_throughput_req_per_s": ideal_throughput,
        "throughput_retained_vs_ideal": retained,
        "throughput_loss_vs_ideal": 1.0 - retained,
        "stranded_capacity_share": float(
            exact.summary["stranded_capacity_share"]
        ),
    }


def aggregate_placement_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, float], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            str(row["placement"]),
            str(row["window_kind"]),
            float(row["window_size"]),
        )
        groups.setdefault(key, []).append(row)

    result: list[dict[str, Any]] = []
    for key, group in sorted(groups.items()):
        eligible = [row for row in group if not bool(row["is_residual"])]
        work_shares = sorted(
            float(row["busiest_work_owner_share"]) for row in eligible
        )
        task_shares = sorted(
            float(row["busiest_task_owner_share"]) for row in eligible
        )
        retained = sorted(
            float(row["throughput_retained_vs_ideal"]) for row in eligible
        )
        losses = sorted(float(row["throughput_loss_vs_ideal"]) for row in eligible)
        static_drain_total = sum(float(row["static_drain_s"]) for row in eligible)
        ideal_drain_total = sum(
            float(row["ideal_balanced_drain_s"]) for row in eligible
        )
        logical_total = sum(
            int(row["logical_request_count"]) for row in eligible
        )
        result.append(
            {
                "placement": key[0],
                "placement_display_name": eligible[0]["placement_display_name"],
                "placement_family": eligible[0]["placement_family"],
                "window_kind": key[1],
                "window_size": key[2],
                "window_count": len(eligible),
                "logical_request_count_total": logical_total,
                "mean_requests_per_window": mean(
                    int(row["logical_request_count"]) for row in eligible
                ),
                "mean_physical_tasks_per_window": mean(
                    int(row["physical_task_count"]) for row in eligible
                ),
                "busiest_task_share_p50": _percentile(task_shares, 0.50),
                "busiest_task_share_p95": _percentile(task_shares, 0.95),
                "busiest_work_share_p50": _percentile(work_shares, 0.50),
                "busiest_work_share_p95": _percentile(work_shares, 0.95),
                "busiest_work_share_max": max(work_shares),
                "throughput_retained_mean": mean(retained),
                "throughput_retained_p50": _percentile(retained, 0.50),
                "throughput_retained_p05": _percentile(retained, 0.05),
                "throughput_retained_min": min(retained),
                "throughput_loss_mean": mean(losses),
                "throughput_loss_p50": _percentile(losses, 0.50),
                "throughput_loss_p95": _percentile(losses, 0.95),
                "throughput_loss_max": max(losses),
                "static_aggregate_throughput_req_per_s": (
                    logical_total / static_drain_total
                    if static_drain_total
                    else 0.0
                ),
                "ideal_aggregate_throughput_req_per_s": (
                    logical_total / ideal_drain_total
                    if ideal_drain_total
                    else 0.0
                ),
                "aggregate_throughput_retained_vs_ideal": (
                    ideal_drain_total / static_drain_total
                    if static_drain_total
                    else 1.0
                ),
                "stranded_capacity_share_mean": mean(
                    float(row["stranded_capacity_share"]) for row in eligible
                ),
                "stranded_capacity_share_p95": _percentile(
                    sorted(
                        float(row["stranded_capacity_share"])
                        for row in eligible
                    ),
                    0.95,
                ),
            }
        )
    return result


def aggregate_family_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, float], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            str(row["placement_family"]),
            str(row["window_kind"]),
            float(row["window_size"]),
        )
        groups.setdefault(key, []).append(row)

    identity = {
        "placement",
        "placement_display_name",
        "placement_family",
        "window_kind",
        "window_size",
    }
    result: list[dict[str, Any]] = []
    for key, group in sorted(groups.items()):
        aggregate: dict[str, Any] = {
            "placement_family": key[0],
            "window_kind": key[1],
            "window_size": key[2],
            "placement_count": len(group),
        }
        for field in group[0]:
            if field in identity:
                continue
            values = [float(row[field]) for row in group]
            aggregate[f"{field}_mean"] = mean(values)
            aggregate[f"{field}_std"] = (
                pstdev(values) if len(values) > 1 else 0.0
            )
            aggregate[f"{field}_min"] = min(values)
            aggregate[f"{field}_max"] = max(values)
        result.append(aggregate)
    return result


def validate_results(
    config: NaturalTraceStaticOwnershipConfig,
    source: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    groups: dict[tuple[str, str, float], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            str(row["placement"]),
            str(row["window_kind"]),
            float(row["window_size"]),
        )
        groups.setdefault(key, []).append(row)
    failures: list[str] = []
    expected_requests = int(source["read_requests"])
    expected_bytes = int(source["trace_bytes"])
    for key, group in groups.items():
        request_count = sum(int(row["logical_request_count"]) for row in group)
        byte_count = sum(int(row["logical_bytes"]) for row in group)
        if request_count != expected_requests:
            failures.append(
                f"{key}: {request_count} requests != {expected_requests}"
            )
        if byte_count != expected_bytes:
            failures.append(f"{key}: {byte_count} bytes != {expected_bytes}")
        if any(
            int(row["physical_task_count"]) > int(row["logical_request_count"])
            for row in group
        ):
            failures.append(f"{key}: physical tasks exceed logical requests")
        if any(
            not 1 / config.zone_count - 1e-12
            <= float(row["busiest_work_owner_share"])
            <= 1.0
            for row in group
        ):
            failures.append(f"{key}: invalid busiest-work share")
        if any(
            not 0.0
            <= float(row["throughput_retained_vs_ideal"])
            <= 1.0 + 1e-12
            for row in group
        ):
            failures.append(f"{key}: invalid throughput retention")
        if any(
            not math.isclose(
                float(row["throughput_retained_vs_ideal"]),
                1.0 - float(row["stranded_capacity_share"]),
                abs_tol=1e-10,
            )
            for row in group
        ):
            failures.append(f"{key}: retention and capacity do not agree")
    return {
        "passed": not failures,
        "failures": failures,
        "checked_window_configurations": len(groups),
        "exact_static_zone_replay": True,
        "request_and_byte_conservation": not any(
            "requests !=" in failure or "bytes !=" in failure
            for failure in failures
        ),
        "balanced_reference": "same productive cycle time divided across 8 owners",
    }


def build_findings(
    config: NaturalTraceStaticOwnershipConfig,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    findings: dict[str, Any] = {}
    for row in rows:
        family = str(row["placement_family"])
        kind = str(row["window_kind"])
        if kind == "request_count":
            label = f"{int(float(row['window_size']))}_requests"
        elif kind == "time":
            label = f"{float(row['window_size']):g}_seconds"
        else:
            label = "full_trace"
        findings.setdefault(family, {})[label] = {
            "placement_count": int(float(row["placement_count"])),
            "window_count": float(row["window_count_mean"]),
            "busiest_work_share_p50": row[
                "busiest_work_share_p50_mean"
            ],
            "busiest_work_share_p95": row[
                "busiest_work_share_p95_mean"
            ],
            "aggregate_throughput_retained_vs_ideal": row[
                "aggregate_throughput_retained_vs_ideal_mean"
            ],
            "aggregate_throughput_loss_vs_ideal": (
                1.0
                - float(
                    row[
                        "aggregate_throughput_retained_vs_ideal_mean"
                    ]
                )
            ),
            "throughput_loss_p95": row["throughput_loss_p95_mean"],
            "stranded_capacity_share_mean": row[
                "stranded_capacity_share_mean_mean"
            ],
        }
    return findings


def write_natural_trace_static_ownership_outputs(
    config: NaturalTraceStaticOwnershipConfig,
    result: NaturalTraceStaticOwnershipResult,
) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    _write_rows(config.output_dir / "window_summary.csv", result.window_rows)
    _write_rows(
        config.output_dir / "placement_summary.csv",
        result.placement_rows,
    )
    _write_rows(config.output_dir / "family_summary.csv", result.family_rows)
    with (config.output_dir / "config.json").open("w", encoding="utf-8") as handle:
        json.dump(config.to_json_dict(), handle, indent=2)
        handle.write("\n")
    with (config.output_dir / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "config": config.to_json_dict(),
                "source": result.source,
                "validation": result.validation,
                "findings": result.findings,
            },
            handle,
            indent=2,
        )
        handle.write("\n")
    _write_report(
        config.output_dir / "LUN0_STATIC_OWNERSHIP_ANALYSIS_ZH.md",
        result,
    )
    figures_dir = config.output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    _write_figures(result, figures_dir)


def _write_figures(
    result: NaturalTraceStaticOwnershipResult,
    output_dir: Path,
) -> None:
    os.environ.setdefault(
        "MPLCONFIGDIR",
        str(Path("results/.mplconfig").resolve()),
    )
    os.environ.setdefault(
        "XDG_CACHE_HOME",
        str(Path("results/.cache").resolve()),
    )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    plt.rcParams.update(
        {
            "font.size": 11,
            "axes.titlesize": 16,
            "axes.labelsize": 12,
            "legend.fontsize": 10,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )
    ordered_keys = _ordered_finding_keys(result.findings)
    labels = [_finding_label(key) for key in ordered_keys]
    families = [
        ("randomized_hash", "Randomized hash", "#2F6F9F"),
        ("contiguous_lba", "Contiguous LBA", "#D97941"),
    ]
    x = np.arange(len(labels))
    width = 0.34

    fig, ax = plt.subplots(figsize=(12.5, 6.8))
    maximum_p95 = 0.0
    for family_index, (family, display, color) in enumerate(families):
        p50 = [
            result.findings[family][key]["busiest_work_share_p50"] * 100
            for key in ordered_keys
        ]
        p95 = [
            result.findings[family][key]["busiest_work_share_p95"] * 100
            for key in ordered_keys
        ]
        maximum_p95 = max(maximum_p95, max(p95, default=0.0))
        positions = x + (family_index - 0.5) * width
        bars = ax.bar(
            positions,
            p50,
            width,
            color=color,
            label=f"{display}: median",
            zorder=3,
        )
        ax.errorbar(
            positions,
            p50,
            yerr=[np.zeros(len(p50)), np.array(p95) - np.array(p50)],
            fmt="none",
            ecolor="#30343B",
            capsize=5,
            linewidth=1.5,
            label="P95 across windows" if family_index == 0 else None,
            zorder=4,
        )
        for bar, value in zip(bars, p50):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 1.0,
                f"{value:.1f}%",
                ha="center",
                va="bottom",
                fontsize=10,
            )
    ax.axhline(
        12.5,
        color="#60656F",
        linestyle="--",
        linewidth=1.5,
        label="Perfectly balanced owner share (12.5%)",
    )
    ax.set_title(
        "Natural ownership skew depends on placement and control scale"
    )
    ax.set_ylabel("Busiest owner share of post-merge work (%)")
    ax.set_xticks(x, labels)
    ax.set_ylim(0, min(100, max(35, maximum_p95 + 10)))
    ax.grid(axis="y", color="#D9DDE3", alpha=0.75, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncol=2, loc="upper right")
    fig.tight_layout()
    _save_figure(fig, output_dir, "fig1_natural_owner_skew")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12.5, 6.8))
    for family_index, (family, display, color) in enumerate(families):
        retained = [
            result.findings[family][key][
                "aggregate_throughput_retained_vs_ideal"
            ]
            * 100
            for key in ordered_keys
        ]
        positions = x + (family_index - 0.5) * width
        bars = ax.bar(
            positions,
            retained,
            width,
            color=color,
            label=display,
            zorder=3,
        )
        for bar, value in zip(bars, retained):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 1.3,
                f"{value:.1f}% retained\n({100 - value:.1f}% loss)",
                ha="center",
                va="bottom",
                fontsize=9.5,
            )
    ax.axhline(
        100,
        color="#60656F",
        linestyle="--",
        linewidth=1.5,
        label="Perfect work balance",
    )
    ax.set_title(
        "Fixed ownership converts natural trace skew into throughput loss"
    )
    ax.set_ylabel("Static throughput retained vs. perfect balance (%)")
    ax.set_xticks(x, labels)
    ax.set_ylim(0, 125)
    ax.grid(axis="y", color="#D9DDE3", alpha=0.75, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncol=3, loc="upper center")
    fig.tight_layout()
    _save_figure(fig, output_dir, "fig2_static_throughput_vs_balanced")
    plt.close(fig)


def _ordered_finding_keys(
    findings: dict[str, Any],
) -> list[str]:
    available = set(findings.get("randomized_hash", {}))
    request_keys = sorted(
        (key for key in available if key.endswith("_requests")),
        key=lambda key: int(key.split("_", 1)[0]),
    )
    time_keys = sorted(
        (key for key in available if key.endswith("_seconds")),
        key=lambda key: float(key.split("_", 1)[0]),
    )
    return request_keys + time_keys + (
        ["full_trace"] if "full_trace" in available else []
    )


def _finding_label(key: str) -> str:
    if key.endswith("_requests"):
        return f"{int(key.split('_', 1)[0]):,}-request\nbatch"
    if key.endswith("_seconds"):
        return f"{float(key.split('_', 1)[0]):g}-second\nwindow"
    return "Full one-hour\ntrace"


def _save_figure(
    fig: Any,
    output_dir: Path,
    stem: str,
) -> None:
    fig.savefig(output_dir / f"{stem}.png", dpi=180)
    fig.savefig(output_dir / f"{stem}.pdf")


def _write_report(
    path: Path,
    result: NaturalTraceStaticOwnershipResult,
) -> None:
    lines = [
        "# LUN0 Natural Trace under Static Ownership",
        "",
        "## 問題",
        "",
        "將 `2016022211-LUN0.csv` 保留自然 timestamp order 並做 window-local merge 後，",
        "strict static ownership 的 work skew 有多大？相對完全平均的理想 lower bound，",
        "throughput 會保留多少？",
        "",
        "## 實驗契約",
        "",
        f"- Trace reads：{result.source['read_requests']:,}。",
        f"- Trace span：{result.source['trace_span_s'] / 60:.1f} minutes。",
        "- 每個 window 以 batch mode replay；timestamp 用來維持順序與切 time windows，",
        "  window 內所有 tasks 在 time 0 ready。",
        "- Static case 使用 exact 8-zone shuttle/reader simulator。",
        "- Ideal balanced reference 將同一批 exact productive cycle time 完全平均除以 8；",
        "  它是 throughput upper bound，不是 physically realizable policy。",
        "- LUN trace 沒有真實 platter mapping，因此 randomized hash 與 contiguous-LBA",
        "  sensitivity 必須分開解讀。",
        "",
    ]
    for family, title in (
        ("randomized_hash", "Randomized-hash placement"),
        ("contiguous_lba", "Contiguous-LBA sensitivity"),
    ):
        lines.extend([f"## {title}", ""])
        rows = result.findings.get(family, {})
        lines.extend(
            [
                "| Scale | P50 busiest work | P95 busiest work | Aggregate throughput retained | Aggregate loss |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for label, row in rows.items():
            lines.append(
                f"| {label.replace('_', ' ')} "
                f"| {row['busiest_work_share_p50'] * 100:.1f}% "
                f"| {row['busiest_work_share_p95'] * 100:.1f}% "
                f"| {row['aggregate_throughput_retained_vs_ideal'] * 100:.1f}% "
                f"| {row['aggregate_throughput_loss_vs_ideal'] * 100:.1f}% |"
            )
        lines.append("")
    lines.extend(
        [
            "## Evidence boundary",
            "",
            "- 數值是 static batch-drain throughput，不是 online arrival-limited throughput。",
            "- Randomized hash 是缺少真實 mapping 時的 primary assumption。",
            "- Contiguous LBA 是 placement-locality sensitivity bound，不能當成 deployed Silica mapping。",
            "- 完全平均 reference 不含 rebalancing travel、boundary change 或 work-stealing overhead。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _panel_config(
    config: NaturalTraceSkewConfig,
    batch_size: int,
) -> PanelStaticZoneConfig:
    return PanelStaticZoneConfig(
        output_dir=config.output_dir,
        seed=0,
        geometry=config.geometry,
        movement=config.movement,
        timing=config.timing,
        workload=PanelWorkloadConfig(
            batch_size=batch_size,
            request_size_bytes=1,
            request_merge=True,
        ),
    )


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    position = quantile * (len(values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    weight = position - lower
    return values[lower] * (1.0 - weight) + values[upper] * weight


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _resolve_path(value: str | Path, base_dir: Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (base_dir / path).resolve()
