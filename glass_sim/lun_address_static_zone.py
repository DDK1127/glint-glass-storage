from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import csv
import hashlib
import json
from pathlib import Path
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
from .trace import TraceRequest, iter_trace


@dataclass(frozen=True)
class LunAddressStaticZoneConfig:
    output_dir: Path
    source_trace_path: Path
    batch_trace_path: Path
    expected_source_sha256: str
    expected_batch_sha256: str
    batch_request_limit: int
    stripe_bytes: int
    geometry: PanelGeometryConfig
    movement: PanelMovementConfig
    timing: PanelTimingConfig

    @property
    def zone_count(self) -> int:
        return self.geometry.levels // self.geometry.zone_height_racks * 2

    @property
    def zone_capacity(self) -> int:
        return self.geometry.zone_height_racks * self.geometry.slots_per_half

    @property
    def platter_count(self) -> int:
        return self.zone_count * self.zone_capacity

    def validate(self) -> None:
        self.geometry.validate()
        self.movement.validate()
        self.timing.validate()
        if not self.source_trace_path.is_file():
            raise ValueError(f"source LUN trace does not exist: {self.source_trace_path}")
        if not self.batch_trace_path.is_file():
            raise ValueError(f"LUN batch does not exist: {self.batch_trace_path}")
        for name, value in (
            ("expected_source_sha256", self.expected_source_sha256),
            ("expected_batch_sha256", self.expected_batch_sha256),
        ):
            if len(value) != 64:
                raise ValueError(f"{name} must contain 64 hexadecimal characters")
            try:
                int(value, 16)
            except ValueError as exc:
                raise ValueError(f"{name} must be hexadecimal") from exc
        if self.batch_request_limit <= 0:
            raise ValueError("batch_request_limit must be positive")
        if self.stripe_bytes <= 0:
            raise ValueError("stripe_bytes must be positive")
        if self.zone_count != 8:
            raise ValueError("the LUN address experiment requires exactly eight zones")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "output_dir": portable_path(self.output_dir),
            "source_trace_path": portable_path(self.source_trace_path),
            "batch_trace_path": portable_path(self.batch_trace_path),
            "expected_source_sha256": self.expected_source_sha256,
            "expected_batch_sha256": self.expected_batch_sha256,
            "batch_request_limit": self.batch_request_limit,
            "stripe_bytes": self.stripe_bytes,
            "geometry": asdict(self.geometry),
            "movement": asdict(self.movement),
            "timing": asdict(self.timing),
            "scope": {
                "fixed_contiguous_address_zones": True,
                "batch_wide_platter_merge": True,
                "adaptive_zones": False,
                "work_stealing": False,
                "synthetic_request_skew": False,
            },
        }


@dataclass(frozen=True)
class LunAddressStaticZoneResult:
    source: dict[str, Any]
    summary: dict[str, Any]
    zone_rows: list[dict[str, Any]]
    boundary_rows: list[dict[str, Any]]
    validation: dict[str, Any]


def load_lun_address_static_zone_config(
    path: str | Path,
) -> LunAddressStaticZoneConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    root = repository_root_for_config(config_path)
    config = LunAddressStaticZoneConfig(
        output_dir=_resolve_path(raw["output_dir"], root),
        source_trace_path=_resolve_path(raw["source_trace_path"], root),
        batch_trace_path=_resolve_path(raw["batch_trace_path"], root),
        expected_source_sha256=str(raw["expected_source_sha256"]).lower(),
        expected_batch_sha256=str(raw["expected_batch_sha256"]).lower(),
        batch_request_limit=int(raw["batch_request_limit"]),
        stripe_bytes=int(raw["stripe_bytes"]),
        geometry=PanelGeometryConfig(**raw["geometry"]),
        movement=PanelMovementConfig(**raw["movement"]),
        timing=PanelTimingConfig(**raw["timing"]),
    )
    config.validate()
    return config


def run_lun_address_static_zone(
    config: LunAddressStaticZoneConfig,
) -> LunAddressStaticZoneResult:
    config.validate()
    source_sha256 = _sha256(config.source_trace_path)
    batch_sha256 = _sha256(config.batch_trace_path)
    if source_sha256 != config.expected_source_sha256:
        raise ValueError(
            f"source checksum mismatch: expected {config.expected_source_sha256}, "
            f"got {source_sha256}"
        )
    if batch_sha256 != config.expected_batch_sha256:
        raise ValueError(
            f"batch checksum mismatch: expected {config.expected_batch_sha256}, "
            f"got {batch_sha256}"
        )

    address_stats = _scan_source_address_range(config)
    batch = _load_batch(config)
    simulator = PanelStaticZoneSimulator(_panel_config(config))
    panel_requests = [
        _map_request(config, simulator, request, address_stats)
        for request in batch
    ]
    merged = merge_panel_requests(panel_requests)
    simulation = simulator.run(merged)
    zone_rows = _zone_rows(config, panel_requests, simulation.zone_rows)
    boundary_rows = _boundary_rows(config, address_stats)
    summary = _summary(config, batch, merged, simulation.summary, zone_rows)
    validation = _validate(
        config,
        batch,
        panel_requests,
        merged,
        simulation.summary,
        boundary_rows,
        address_stats,
    )
    if not validation["passed"]:
        raise RuntimeError(f"LUN address static-zone validation failed: {validation}")

    source = {
        "source_trace_path": portable_path(config.source_trace_path),
        "source_sha256": source_sha256,
        "batch_trace_path": portable_path(config.batch_trace_path),
        "batch_sha256": batch_sha256,
        **address_stats,
        "batch_request_count": len(batch),
        "batch_logical_bytes": sum(request.size_bytes for request in batch),
        "batch_span_s": batch[-1].arrival_s - batch[0].arrival_s,
        "batch_unique_offsets": len({request.offset for request in batch}),
        "batch_unique_stripes": len(
            {request.offset // config.stripe_bytes for request in batch}
        ),
    }
    return LunAddressStaticZoneResult(
        source=source,
        summary=summary,
        zone_rows=zone_rows,
        boundary_rows=boundary_rows,
        validation=validation,
    )


def write_lun_address_static_zone_outputs(
    config: LunAddressStaticZoneConfig,
    result: LunAddressStaticZoneResult,
) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(config.output_dir / "zone_summary.csv", result.zone_rows)
    _write_csv(
        config.output_dir / "address_zone_boundaries.csv",
        result.boundary_rows,
    )
    with (config.output_dir / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "config": config.to_json_dict(),
                "source": result.source,
                "summary": result.summary,
                "validation": result.validation,
            },
            handle,
            indent=2,
        )
        handle.write("\n")
    _write_report(
        config.output_dir / "LUN_ADDRESS_STATIC_ZONE_ZH.md",
        config,
        result,
    )
    figures_dir = config.output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    _write_figures(config, result, figures_dir)


def map_stripe_to_position(
    stripe_id: int,
    min_stripe_id: int,
    max_stripe_id: int,
    platter_count: int,
) -> int:
    if platter_count <= 0:
        raise ValueError("platter_count must be positive")
    if max_stripe_id < min_stripe_id:
        raise ValueError("max_stripe_id cannot be smaller than min_stripe_id")
    if not min_stripe_id <= stripe_id <= max_stripe_id:
        raise ValueError("stripe_id lies outside the fixed address range")
    distance = max_stripe_id - min_stripe_id
    if distance == 0:
        return 0
    return (stripe_id - min_stripe_id) * (platter_count - 1) // distance


def _scan_source_address_range(
    config: LunAddressStaticZoneConfig,
) -> dict[str, Any]:
    min_stripe: int | None = None
    max_stripe: int | None = None
    read_count = 0
    min_offset: int | None = None
    max_offset: int | None = None
    for request in iter_trace(config.source_trace_path):
        if request.io_type != "R":
            continue
        stripe = request.offset // config.stripe_bytes
        min_stripe = stripe if min_stripe is None else min(min_stripe, stripe)
        max_stripe = stripe if max_stripe is None else max(max_stripe, stripe)
        min_offset = (
            request.offset
            if min_offset is None
            else min(min_offset, request.offset)
        )
        max_offset = (
            request.offset
            if max_offset is None
            else max(max_offset, request.offset)
        )
        read_count += 1
    if min_stripe is None or max_stripe is None:
        raise ValueError("source LUN trace contains no reads")
    return {
        "source_read_count": read_count,
        "observed_min_offset": min_offset,
        "observed_max_offset": max_offset,
        "min_stripe_id": min_stripe,
        "max_stripe_id": max_stripe,
        "observed_address_span_bytes": (
            (max_stripe - min_stripe + 1) * config.stripe_bytes
        ),
        "address_bounds_source": "all reads in the complete LUN0 trace",
    }


def _load_batch(config: LunAddressStaticZoneConfig) -> list[TraceRequest]:
    reads = [
        request
        for request in iter_trace(config.batch_trace_path)
        if request.io_type == "R"
    ]
    reads.sort(key=lambda request: (request.arrival_s, request.index))
    if len(reads) < config.batch_request_limit:
        raise ValueError(
            f"batch contains {len(reads)} reads, fewer than "
            f"{config.batch_request_limit}"
        )
    return reads[: config.batch_request_limit]


def _map_request(
    config: LunAddressStaticZoneConfig,
    simulator: PanelStaticZoneSimulator,
    request: TraceRequest,
    address_stats: dict[str, Any],
) -> Any:
    stripe_id = request.offset // config.stripe_bytes
    platter_id = map_stripe_to_position(
        stripe_id,
        int(address_stats["min_stripe_id"]),
        int(address_stats["max_stripe_id"]),
        config.platter_count,
    )
    zone_id, local_platter = divmod(platter_id, config.zone_capacity)
    local_level, slot = divmod(
        local_platter,
        config.geometry.slots_per_half,
    )
    return replace(
        simulator.make_request(
            request_index=request.index,
            zone_id=zone_id,
            local_level=local_level,
            slot_in_half=slot,
            size_bytes=request.size_bytes,
        ),
        arrival_s=0.0,
    )


def _zone_rows(
    config: LunAddressStaticZoneConfig,
    panel_requests: list[Any],
    simulation_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    logical_counts = [0] * config.zone_count
    logical_bytes = [0] * config.zone_count
    for request in panel_requests:
        logical_counts[request.zone_id] += 1
        logical_bytes[request.zone_id] += request.size_bytes
    total_requests = sum(logical_counts)
    total_bytes = sum(logical_bytes)
    total_work = sum(float(row["active_cycle_s"]) for row in simulation_rows)
    total_tasks = sum(int(row["glass_service_count"]) for row in simulation_rows)
    return [
        {
            "zone_id": int(row["zone_id"]),
            "logical_request_count": logical_counts[int(row["zone_id"])],
            "logical_request_share": (
                logical_counts[int(row["zone_id"])] / total_requests
            ),
            "logical_bytes": logical_bytes[int(row["zone_id"])],
            "logical_byte_share": (
                logical_bytes[int(row["zone_id"])] / total_bytes
                if total_bytes
                else 0.0
            ),
            "physical_task_count": int(row["glass_service_count"]),
            "physical_task_share": (
                int(row["glass_service_count"]) / total_tasks
                if total_tasks
                else 0.0
            ),
            "active_work_s": float(row["active_cycle_s"]),
            "post_merge_work_share": (
                float(row["active_cycle_s"]) / total_work
                if total_work
                else 0.0
            ),
            "completion_s": float(row["completion_s"]),
        }
        for row in simulation_rows
    ]


def _boundary_rows(
    config: LunAddressStaticZoneConfig,
    address_stats: dict[str, Any],
) -> list[dict[str, Any]]:
    min_stripe = int(address_stats["min_stripe_id"])
    max_stripe = int(address_stats["max_stripe_id"])
    by_zone: list[list[int]] = [[] for _ in range(config.zone_count)]
    for stripe in range(min_stripe, max_stripe + 1):
        position = map_stripe_to_position(
            stripe,
            min_stripe,
            max_stripe,
            config.platter_count,
        )
        by_zone[position // config.zone_capacity].append(stripe)
    return [
        {
            "zone_id": zone_id,
            "start_stripe_id": stripes[0],
            "end_stripe_id": stripes[-1],
            "start_offset_bytes": stripes[0] * config.stripe_bytes,
            "end_offset_exclusive_bytes": (
                (stripes[-1] + 1) * config.stripe_bytes
            ),
            "stripe_count": len(stripes),
            "position_start": zone_id * config.zone_capacity,
            "position_end": (zone_id + 1) * config.zone_capacity - 1,
        }
        for zone_id, stripes in enumerate(by_zone)
    ]


def _summary(
    config: LunAddressStaticZoneConfig,
    batch: list[TraceRequest],
    merged: list[Any],
    simulation_summary: dict[str, Any],
    zone_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    max_logical = max(
        float(row["logical_request_share"]) for row in zone_rows
    )
    max_work = max(float(row["post_merge_work_share"]) for row in zone_rows)
    efficiency = float(simulation_summary["static_capacity_efficiency"])
    return {
        "logical_request_count": len(batch),
        "logical_bytes": sum(request.size_bytes for request in batch),
        "physical_task_count": len(merged),
        "requests_per_physical_task": len(batch) / len(merged),
        "zone_count": config.zone_count,
        "shuttle_count": simulation_summary["shuttle_count"],
        "reader_count": simulation_summary["reader_count"],
        "balanced_zone_share": 1 / config.zone_count,
        "max_zone_logical_share": max_logical,
        "logical_busiest_zone_over_mean": max_logical * config.zone_count,
        "max_zone_post_merge_work_share": max_work,
        "work_busiest_zone_over_mean": max_work * config.zone_count,
        "static_capacity_efficiency": efficiency,
        "static_throughput_loss_vs_same_work_ideal": 1.0 - efficiency,
        "ownership_slowdown_vs_ideal": simulation_summary[
            "ownership_slowdown_vs_ideal"
        ],
        "system_drain_s": simulation_summary["system_drain_s"],
        "ideal_balanced_cycle_lower_bound_s": simulation_summary[
            "ideal_balanced_cycle_lower_bound_s"
        ],
        "logical_throughput_req_per_s": simulation_summary[
            "throughput_req_per_s_drained"
        ],
        "stranded_capacity_s": simulation_summary["stranded_capacity_s"],
    }


def _validate(
    config: LunAddressStaticZoneConfig,
    batch: list[TraceRequest],
    panel_requests: list[Any],
    merged: list[Any],
    simulation_summary: dict[str, Any],
    boundary_rows: list[dict[str, Any]],
    address_stats: dict[str, Any],
) -> dict[str, Any]:
    failures: list[str] = []
    logical_bytes = sum(request.size_bytes for request in batch)
    if len(panel_requests) != len(batch):
        failures.append("address mapping changed the logical request count")
    if sum(request.size_bytes for request in panel_requests) != logical_bytes:
        failures.append("address mapping changed logical bytes")
    if sum(request.merged_request_count for request in merged) != len(batch):
        failures.append("batch-wide merge changed the logical request count")
    if sum(request.size_bytes for request in merged) != logical_bytes:
        failures.append("batch-wide merge changed logical bytes")
    if len({request.platter_id for request in merged}) != len(merged):
        failures.append("merged platter IDs are not unique")
    if simulation_summary["zone_count"] != config.zone_count:
        failures.append("zone count changed")
    if simulation_summary["shuttle_count"] != config.zone_count:
        failures.append("shuttle count changed")
    if simulation_summary["reader_count"] != config.zone_count:
        failures.append("reader count changed")
    if [int(row["zone_id"]) for row in boundary_rows] != list(
        range(config.zone_count)
    ):
        failures.append("address boundaries do not contain exactly eight zones")
    for first, second in zip(boundary_rows, boundary_rows[1:]):
        if int(first["end_stripe_id"]) + 1 != int(second["start_stripe_id"]):
            failures.append("address zone boundaries are not contiguous")
    if int(boundary_rows[0]["start_stripe_id"]) != int(
        address_stats["min_stripe_id"]
    ):
        failures.append("address boundaries do not start at the observed minimum")
    if int(boundary_rows[-1]["end_stripe_id"]) != int(
        address_stats["max_stripe_id"]
    ):
        failures.append("address boundaries do not end at the observed maximum")
    mapping: dict[int, int] = {}
    for request, mapped in zip(batch, panel_requests):
        stripe = request.offset // config.stripe_bytes
        previous = mapping.setdefault(stripe, mapped.platter_id)
        if previous != mapped.platter_id:
            failures.append("one address stripe mapped to multiple positions")
            break
    return {
        "passed": not failures,
        "failures": failures,
        "source_checksum_matches": True,
        "batch_checksum_matches": True,
        "logical_requests_preserved": len(panel_requests) == len(batch),
        "logical_bytes_preserved": (
            sum(request.size_bytes for request in merged) == logical_bytes
        ),
        "fixed_contiguous_zone_boundaries": not any(
            "boundaries" in failure for failure in failures
        ),
        "same_address_has_fixed_position": not any(
            "address stripe" in failure for failure in failures
        ),
    }


def _panel_config(
    config: LunAddressStaticZoneConfig,
) -> PanelStaticZoneConfig:
    return PanelStaticZoneConfig(
        output_dir=config.output_dir,
        seed=0,
        geometry=config.geometry,
        movement=config.movement,
        timing=config.timing,
        workload=PanelWorkloadConfig(
            batch_size=config.batch_request_limit,
            request_size_bytes=1,
            request_merge=True,
        ),
    )


def _write_report(
    path: Path,
    config: LunAddressStaticZoneConfig,
    result: LunAddressStaticZoneResult,
) -> None:
    summary = result.summary
    lines = [
        "# LUN0 Address-Mapped Static-Zone Experiment",
        "",
        "## 實驗做法",
        "",
        "- 使用完整 `2016022211-LUN0.csv` 的 observed read-address range，"
        "事先切成 8 個等 address-range、連續且不重疊的 static zones。",
        f"- 每個 {config.stripe_bytes // (1024 * 1024)} MiB address stripe "
        "固定映射到 6,400 個 panel positions 之一。",
        f"- 評估 timestamp 排序後最前面的 {result.source['batch_request_count']:,} "
        "筆 reads；沒有修改 request order、offset、size 或熱門程度。",
        "- 所有 requests 視為同一 batch，映射後才對同一 platter 做 merge。",
        "- 不包含 hash placement、application affinity、adaptive boundary 或 work stealing。",
        "",
        "## 結果",
        "",
        f"- Balanced reference：每個 zone 應承擔 {summary['balanced_zone_share'] * 100:.1f}% work。",
        f"- 最忙 zone 的原始 requests：{summary['max_zone_logical_share'] * 100:.2f}% "
        f"（平均的 {summary['logical_busiest_zone_over_mean']:.2f}x）。",
        f"- Merge 後最忙 zone 的 physical work："
        f"{summary['max_zone_post_merge_work_share'] * 100:.2f}% "
        f"（平均的 {summary['work_busiest_zone_over_mean']:.2f}x）。",
        f"- Physical platter tasks：{summary['physical_task_count']:,}，"
        f"平均每次 service 合併 {summary['requests_per_physical_task']:.2f} requests。",
        f"- Static capacity efficiency：{summary['static_capacity_efficiency'] * 100:.2f}%。",
        f"- Throughput loss vs. same-work ideal："
        f"{summary['static_throughput_loss_vs_same_work_ideal'] * 100:.2f}%。",
        f"- Batch drain time：{summary['system_drain_s'] / 3600:.2f} hours。",
        "",
        "## 解讀邊界",
        "",
        "這個結果直接衡量 LUN address locality 在固定 contiguous zones 下造成的失衡。"
        "Zone boundaries 使用完整 trace 的 observed range，因此不會隨這個 batch 調整。",
        "",
        "但 LUN offset 仍是 logical address，不是 Microsoft 公開的真實 "
        "Silica platter placement；contiguous address-to-position mapping 是本實驗"
        "明確採用的 placement assumption。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_figures(
    config: LunAddressStaticZoneConfig,
    result: LunAddressStaticZoneResult,
    figures_dir: Path,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch, Rectangle

    balanced = 100 / config.zone_count
    logical = [
        float(row["logical_request_share"]) * 100
        for row in result.zone_rows
    ]
    work = [
        float(row["post_merge_work_share"]) * 100
        for row in result.zone_rows
    ]

    def fill_color(share: float) -> str:
        if share > balanced * 1.15:
            return "#E88471"
        if share < balanced * 0.85:
            return "#D5D5D5"
        return "#B9D2E8"

    fig, axes = plt.subplots(1, 2, figsize=(9.4, 5.0))
    for axis, values, title in zip(
        axes,
        (logical, work),
        ("Original user requests", "Post-merge physical work"),
    ):
        for zone_id, share in enumerate(values):
            column = 0 if zone_id < 4 else 1
            row = zone_id if zone_id < 4 else zone_id - 4
            x = column * 1.14
            y = 3 - row
            axis.add_patch(
                Rectangle(
                    (x, y),
                    1.0,
                    0.88,
                    facecolor=fill_color(share),
                    edgecolor="#333333",
                    linewidth=1.0,
                )
            )
            axis.text(
                x + 0.5,
                y + 0.44,
                f"Zone {zone_id}\n{share:.1f}%",
                ha="center",
                va="center",
                fontsize=10,
            )
        axis.plot(
            [1.07, 1.07],
            [-0.05, 3.93],
            color="#777777",
            linewidth=1.0,
            linestyle=":",
        )
        axis.set_xlim(-0.08, 2.22)
        axis.set_ylim(-0.18, 4.08)
        axis.set_aspect("equal")
        axis.axis("off")
        axis.set_title(title, fontsize=12, pad=8)
    fig.suptitle(
        f"Fixed address mapping across 8 static zones (balanced = {balanced:.1f}%)",
        fontsize=14,
        y=0.98,
    )
    fig.legend(
        handles=[
            Patch(facecolor="#B9D2E8", edgecolor="#333333", label="Near balanced"),
            Patch(facecolor="#E88471", edgecolor="#333333", label="Busy"),
            Patch(facecolor="#D5D5D5", edgecolor="#333333", label="Cold"),
        ],
        loc="lower center",
        ncol=3,
        frameon=False,
    )
    fig.tight_layout(rect=(0, 0.09, 1, 0.93))
    _save(fig, figures_dir, "fig1_address_mapped_zone_skew")

    completion = [
        float(row["completion_s"]) / 3600
        for row in result.zone_rows
    ]
    loss = (
        float(
            result.summary[
                "static_throughput_loss_vs_same_work_ideal"
            ]
        )
        * 100
    )
    fig, axis = plt.subplots(figsize=(7.4, 4.6))
    bars = axis.barh(
        range(config.zone_count),
        completion,
        color=[fill_color(value) for value in work],
        edgecolor="#333333",
    )
    axis.invert_yaxis()
    axis.set_yticks(range(config.zone_count), [f"Zone {index}" for index in range(config.zone_count)])
    axis.set_xlabel("Zone completion time (hours)")
    axis.set_title(
        "The batch waits for the slowest fixed owner "
        f"({loss:.1f}% loss vs same-work ideal)"
    )
    axis.grid(axis="x", color="#DDDDDD", linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines[["top", "right"]].set_visible(False)
    for bar, value in zip(bars, completion):
        axis.text(
            value,
            bar.get_y() + bar.get_height() / 2,
            f" {value:.2f} h",
            va="center",
            fontsize=9,
        )
    fig.tight_layout()
    _save(fig, figures_dir, "fig2_static_zone_completion")


def _save(fig: Any, output_dir: Path, stem: str) -> None:
    for suffix in ("png", "pdf"):
        fig.savefig(
            output_dir / f"{stem}.{suffix}",
            dpi=220,
            bbox_inches="tight",
        )
    fig.clf()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0].keys()),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_path(path: str, root: Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve()
