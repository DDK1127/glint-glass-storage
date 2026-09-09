from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import csv
import gzip
import hashlib
import json
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from .panel_static_zone import (
    PanelGeometryConfig,
    PanelMovementConfig,
    PanelRequest,
    PanelStaticZoneConfig,
    PanelStaticZoneSimulator,
    PanelTimingConfig,
    PanelWorkloadConfig,
)
from .paths import portable_path, repository_root_for_config


UNIFORM_HASH = "uniform_object_hash"
APP_AFFINITY = "application_owner_affinity"
PLACEMENT_ORDER = (UNIFORM_HASH, APP_AFFINITY)


@dataclass(frozen=True)
class AzureBatchAccess:
    index: int
    blob_name: str
    blob_etag: str
    application: str
    size_bytes: int

    @property
    def object_key(self) -> tuple[str, str]:
        return (self.blob_name, self.blob_etag)


@dataclass(frozen=True)
class AzureStaticZonePilotConfig:
    output_dir: Path
    batch_path: Path
    expected_batch_sha256: str
    seeds: tuple[int, ...]
    geometry: PanelGeometryConfig
    movement: PanelMovementConfig
    timing: PanelTimingConfig

    @property
    def zone_count(self) -> int:
        return (
            self.geometry.levels // self.geometry.zone_height_racks
        ) * 2

    @property
    def platter_count(self) -> int:
        return (
            self.zone_count
            * self.geometry.zone_height_racks
            * self.geometry.slots_per_half
        )

    def validate(self) -> None:
        self.geometry.validate()
        self.movement.validate()
        self.timing.validate()
        if not self.batch_path.is_file():
            raise ValueError(f"Azure pilot batch does not exist: {self.batch_path}")
        if len(self.expected_batch_sha256) != 64:
            raise ValueError("expected_batch_sha256 must contain 64 hexadecimal characters")
        try:
            int(self.expected_batch_sha256, 16)
        except ValueError as exc:
            raise ValueError("expected_batch_sha256 must be hexadecimal") from exc
        if not self.seeds or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds must be nonempty and unique")
        if self.zone_count != 8:
            raise ValueError("the Azure pilot requires exactly eight static zones")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "output_dir": portable_path(self.output_dir),
            "batch_path": portable_path(self.batch_path),
            "expected_batch_sha256": self.expected_batch_sha256,
            "seeds": list(self.seeds),
            "geometry": asdict(self.geometry),
            "movement": asdict(self.movement),
            "timing": asdict(self.timing),
            "scope": {
                "static_non_overlapping_ownership": True,
                "batch_wide_platter_merge": True,
                "adaptive_zones": False,
                "work_stealing": False,
                "zipf": False,
            },
        }


@dataclass(frozen=True)
class AzureStaticZonePilotResult:
    source: dict[str, Any]
    run_rows: list[dict[str, Any]]
    aggregate_rows: list[dict[str, Any]]
    zone_rows: list[dict[str, Any]]
    validation: dict[str, Any]


def load_azure_static_zone_pilot_config(
    path: str | Path,
) -> AzureStaticZonePilotConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    root = repository_root_for_config(config_path)
    output_dir = _resolve_path(raw["output_dir"], root)
    config = AzureStaticZonePilotConfig(
        output_dir=output_dir,
        batch_path=_resolve_path(raw["batch_path"], root),
        expected_batch_sha256=str(raw["expected_batch_sha256"]).lower(),
        seeds=tuple(int(seed) for seed in raw["seeds"]),
        geometry=PanelGeometryConfig(**raw["geometry"]),
        movement=PanelMovementConfig(**raw["movement"]),
        timing=PanelTimingConfig(**raw["timing"]),
    )
    config.validate()
    return config


def run_azure_static_zone_pilot(
    config: AzureStaticZonePilotConfig,
) -> AzureStaticZonePilotResult:
    config.validate()
    batch_sha256 = _sha256(config.batch_path)
    if batch_sha256 != config.expected_batch_sha256:
        raise ValueError(
            "batch checksum mismatch: "
            f"expected {config.expected_batch_sha256}, got {batch_sha256}"
        )
    accesses = _load_batch(config.batch_path)
    unique_objects: dict[tuple[str, str], int] = {}
    for access in accesses:
        existing_size = unique_objects.setdefault(
            access.object_key,
            access.size_bytes,
        )
        if existing_size != access.size_bytes:
            raise ValueError(
                "blob version has inconsistent sizes within the batch: "
                f"{access.object_key}"
            )
    source = {
        "batch_path": portable_path(config.batch_path),
        "batch_sha256": batch_sha256,
        "logical_request_count": len(accesses),
        "logical_bytes": sum(access.size_bytes for access in accesses),
        "unique_blob_versions": len(unique_objects),
        "unique_blob_version_bytes": sum(unique_objects.values()),
        "top_application_request_share": _top_application_share(accesses),
    }

    run_rows: list[dict[str, Any]] = []
    zone_rows: list[dict[str, Any]] = []
    failures: list[str] = []
    signatures: dict[int, dict[str, str]] = {}
    for seed in config.seeds:
        signatures[seed] = {}
        for placement in PLACEMENT_ORDER:
            simulator = PanelStaticZoneSimulator(_panel_config(config, seed))
            physical_requests, mapping_signature = _build_physical_requests(
                config,
                simulator,
                accesses,
                placement,
                seed,
            )
            result = simulator.run(physical_requests)
            run_row = _run_row(
                config,
                source,
                placement,
                seed,
                result,
            )
            run_rows.append(run_row)
            signatures[seed][placement] = mapping_signature
            zone_rows.extend(
                _zone_detail_rows(
                    placement,
                    seed,
                    result.zone_rows,
                )
            )
            _validate_run(
                config,
                source,
                placement,
                seed,
                physical_requests,
                result,
                failures,
            )

    aggregate_rows = _aggregate_rows(run_rows)
    validation = {
        "passed": not failures,
        "failures": failures,
        "batch_checksum_matches": True,
        "logical_trace_shared_across_placements": True,
        "fixed_zone_count": config.zone_count,
        "fixed_shuttle_count": config.zone_count,
        "fixed_reader_count": config.zone_count,
        "mapping_signatures": signatures,
    }
    return AzureStaticZonePilotResult(
        source=source,
        run_rows=run_rows,
        aggregate_rows=aggregate_rows,
        zone_rows=zone_rows,
        validation=validation,
    )


def write_azure_static_zone_pilot_outputs(
    config: AzureStaticZonePilotConfig,
    result: AzureStaticZonePilotResult,
) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(config.output_dir / "run_summary.csv", result.run_rows)
    _write_csv(
        config.output_dir / "aggregate_summary.csv",
        result.aggregate_rows,
    )
    _write_csv(config.output_dir / "zone_summary.csv", result.zone_rows)
    with (config.output_dir / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "config": config.to_json_dict(),
                "source": result.source,
                "validation": result.validation,
                "aggregate_rows": result.aggregate_rows,
            },
            handle,
            indent=2,
        )
        handle.write("\n")
    _write_report(
        config.output_dir / "AZURE_STATIC_ZONE_PILOT_ZH.md",
        config,
        result,
    )
    figures_dir = config.output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    _write_figures(result, figures_dir, config.seeds[0])


def _load_batch(path: Path) -> list[AzureBatchAccess]:
    accesses: list[AzureBatchAccess] = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "AnonBlobName",
            "AnonBlobETag",
            "AnonAppName",
            "BlobBytes",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Azure batch is missing columns: {sorted(missing)}")
        for index, row in enumerate(reader):
            accesses.append(
                AzureBatchAccess(
                    index=index,
                    blob_name=row["AnonBlobName"],
                    blob_etag=row["AnonBlobETag"],
                    application=row["AnonAppName"],
                    size_bytes=int(row["BlobBytes"]),
                )
            )
    if not accesses:
        raise ValueError("Azure pilot batch is empty")
    return accesses


def _build_physical_requests(
    config: AzureStaticZonePilotConfig,
    simulator: PanelStaticZoneSimulator,
    accesses: list[AzureBatchAccess],
    placement: str,
    seed: int,
) -> tuple[list[PanelRequest], str]:
    first_application: dict[tuple[str, str], str] = {}
    groups: dict[int, dict[str, Any]] = {}
    signature = hashlib.sha256()
    zone_capacity = (
        config.geometry.zone_height_racks
        * config.geometry.slots_per_half
    )
    for access in accesses:
        first_application.setdefault(access.object_key, access.application)
        if placement == UNIFORM_HASH:
            platter_id = _hash_u64(
                seed,
                access.blob_name,
                access.blob_etag,
            ) % config.platter_count
        elif placement == APP_AFFINITY:
            owner = _hash_u64(
                seed,
                first_application[access.object_key],
            ) % config.zone_count
            local_platter = _hash_u64(
                seed,
                access.blob_name,
                access.blob_etag,
            ) % zone_capacity
            platter_id = owner * zone_capacity + local_platter
        else:
            raise ValueError(f"unsupported placement: {placement}")
        signature.update(
            f"{access.index}:{platter_id}\n".encode("ascii")
        )
        group = groups.setdefault(
            platter_id,
            {
                "first_index": access.index,
                "logical_count": 0,
                "objects": {},
            },
        )
        group["logical_count"] += 1
        group["objects"].setdefault(
            access.object_key,
            access.size_bytes,
        )

    physical: list[PanelRequest] = []
    for platter_id, group in groups.items():
        zone_id, local_platter = divmod(platter_id, zone_capacity)
        local_level, slot = divmod(
            local_platter,
            config.geometry.slots_per_half,
        )
        request = simulator.make_request(
            request_index=int(group["first_index"]),
            zone_id=zone_id,
            local_level=local_level,
            slot_in_half=slot,
            size_bytes=sum(group["objects"].values()),
        )
        physical.append(
            replace(
                request,
                arrival_s=0.0,
                merged_request_count=int(group["logical_count"]),
            )
        )
    physical.sort(key=lambda request: request.request_index)
    return physical, signature.hexdigest()


def _run_row(
    config: AzureStaticZonePilotConfig,
    source: dict[str, Any],
    placement: str,
    seed: int,
    result: Any,
) -> dict[str, Any]:
    work = [float(row["active_cycle_s"]) for row in result.zone_rows]
    logical = [
        int(row["logical_request_count"])
        for row in result.zone_rows
    ]
    tasks = [int(row["glass_service_count"]) for row in result.zone_rows]
    total_work = sum(work)
    summary = result.summary
    efficiency = float(summary["static_capacity_efficiency"])
    return {
        "placement": placement,
        "placement_label": _placement_label(placement),
        "seed": seed,
        "logical_request_count": source["logical_request_count"],
        "logical_bytes": source["logical_bytes"],
        "unique_blob_versions": source["unique_blob_versions"],
        "physical_task_count": summary["service_operation_count"],
        "physical_unique_bytes": sum(
            detail.size_bytes for detail in result.details
        ),
        "requests_per_physical_task": (
            source["logical_request_count"]
            / summary["service_operation_count"]
        ),
        "max_zone_logical_share": max(logical) / sum(logical),
        "max_zone_task_share": max(tasks) / sum(tasks),
        "max_zone_work_share": max(work) / total_work,
        "busiest_zone_work_over_mean": max(work) / mean(work),
        "static_capacity_efficiency": efficiency,
        "static_throughput_loss_vs_same_work_ideal": 1.0 - efficiency,
        "ownership_slowdown_vs_ideal": summary[
            "ownership_slowdown_vs_ideal"
        ],
        "system_drain_s": summary["system_drain_s"],
        "logical_throughput_req_per_s": summary[
            "throughput_req_per_s_drained"
        ],
        "stranded_capacity_s": summary["stranded_capacity_s"],
        "zone_count": config.zone_count,
        "shuttle_count": summary["shuttle_count"],
        "reader_count": summary["reader_count"],
    }


def _validate_run(
    config: AzureStaticZonePilotConfig,
    source: dict[str, Any],
    placement: str,
    seed: int,
    physical_requests: list[PanelRequest],
    result: Any,
    failures: list[str],
) -> None:
    label = f"{placement}/seed-{seed}"
    if sum(request.merged_request_count for request in physical_requests) != source[
        "logical_request_count"
    ]:
        failures.append(f"{label}: logical request count changed")
    if sum(request.size_bytes for request in physical_requests) != source[
        "unique_blob_version_bytes"
    ]:
        failures.append(f"{label}: unique object bytes changed")
    if len({request.platter_id for request in physical_requests}) != len(
        physical_requests
    ):
        failures.append(f"{label}: physical platter tasks overlap")
    if len(physical_requests) > config.platter_count:
        failures.append(f"{label}: physical task count exceeds panel slots")
    if result.summary["zone_count"] != config.zone_count:
        failures.append(f"{label}: zone count changed")
    if result.summary["shuttle_count"] != config.zone_count:
        failures.append(f"{label}: shuttle count changed")
    if result.summary["reader_count"] != config.zone_count:
        failures.append(f"{label}: reader count changed")
    if not 0.0 < result.summary["static_capacity_efficiency"] <= 1.0:
        failures.append(f"{label}: invalid capacity efficiency")


def _aggregate_rows(
    run_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    metrics = (
        "physical_task_count",
        "requests_per_physical_task",
        "max_zone_logical_share",
        "max_zone_task_share",
        "max_zone_work_share",
        "busiest_zone_work_over_mean",
        "static_capacity_efficiency",
        "static_throughput_loss_vs_same_work_ideal",
        "ownership_slowdown_vs_ideal",
        "system_drain_s",
        "logical_throughput_req_per_s",
        "stranded_capacity_s",
    )
    aggregates: list[dict[str, Any]] = []
    for placement in PLACEMENT_ORDER:
        rows = [row for row in run_rows if row["placement"] == placement]
        aggregate: dict[str, Any] = {
            "placement": placement,
            "placement_label": _placement_label(placement),
            "seed_count": len(rows),
        }
        for metric in metrics:
            values = [float(row[metric]) for row in rows]
            aggregate[f"{metric}_mean"] = mean(values)
            aggregate[f"{metric}_std"] = pstdev(values)
            aggregate[f"{metric}_min"] = min(values)
            aggregate[f"{metric}_max"] = max(values)
        aggregates.append(aggregate)
    return aggregates


def _zone_detail_rows(
    placement: str,
    seed: int,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    total_work = sum(float(row["active_cycle_s"]) for row in rows)
    return [
        {
            "placement": placement,
            "placement_label": _placement_label(placement),
            "seed": seed,
            "zone_id": int(row["zone_id"]),
            "logical_request_count": int(row["logical_request_count"]),
            "physical_task_count": int(row["glass_service_count"]),
            "active_work_s": float(row["active_cycle_s"]),
            "work_share": (
                float(row["active_cycle_s"]) / total_work
                if total_work
                else 0.0
            ),
            "completion_s": float(row["completion_s"]),
        }
        for row in rows
    ]


def _panel_config(
    config: AzureStaticZonePilotConfig,
    seed: int,
) -> PanelStaticZoneConfig:
    return PanelStaticZoneConfig(
        output_dir=config.output_dir,
        seed=seed,
        geometry=config.geometry,
        movement=config.movement,
        timing=config.timing,
        workload=PanelWorkloadConfig(
            batch_size=1,
            request_size_bytes=1,
            placement="uniform_round_robin",
            request_merge=True,
        ),
    )


def _write_report(
    path: Path,
    config: AzureStaticZonePilotConfig,
    result: AzureStaticZonePilotResult,
) -> None:
    rows = {row["placement"]: row for row in result.aggregate_rows}
    uniform = rows[UNIFORM_HASH]
    affinity = rows[APP_AFFINITY]
    text = f"""# Azure 100k Batch Static-Zone Pilot

## 問題

在相同 100,000 筆真實 Azure Blob reads 下，static non-overlapping
ownership 造成多少 post-merge work imbalance？

## Mapping 範圍

- `Uniform object hash`：保守 baseline；blob version 均勻 hash 到
  {config.platter_count:,} 個 panel slots。
- `Application owner affinity`：placement-correlation sensitivity；每個
  blob version 依第一次出現的 application 限制在單一 static owner。
  這不是 production placement 的宣稱。
- 兩者各自與「相同 merged physical work 的 work-conserving ideal」比較。
  因為 mapping 會改變 merge cardinality，不直接用兩者 raw throughput
  相減來宣稱 static-zone gain。

## Dataset 如何處理

1. 從原始 Azure Functions Blob Access Trace 保留 `Read == True` 且
   `BlobBytes` 已知的紀錄，再依 timestamp 穩定排序。
2. 取排序後最前面的 100,000 筆 reads；沒有挑選 hotspot、application、
   region 或 peak interval。
3. 保留所有重複 request，不預先 deduplicate。這個 batch 包含
   {result.source['unique_blob_versions']:,} 個 unique blob versions。
4. 實驗才將 blob versions 映射到 synthetic platter slots，並在整個
   batch 內合併落在同一 platter 的 requests。
5. 100,000 筆 requests 全部視為同一個已到達的 batch；原本約四小時的
   arrival spacing 不用來模擬 queueing。

原始下載檔與 canonical read trace 都沒有被覆寫。Platter mapping 與
application-owner affinity 是實驗模型，不是 Azure dataset 提供的欄位，
也不是 production Silica placement 的宣稱。

## 結果

| Placement | Max logical share | Max post-merge work share | Work max/mean | Throughput loss vs own ideal |
| --- | ---: | ---: | ---: | ---: |
| Uniform object hash | {uniform['max_zone_logical_share_mean'] * 100:.2f}% | {uniform['max_zone_work_share_mean'] * 100:.2f}% | {uniform['busiest_zone_work_over_mean_mean']:.3f}x | {uniform['static_throughput_loss_vs_same_work_ideal_mean'] * 100:.2f}% |
| Application owner affinity | {affinity['max_zone_logical_share_mean'] * 100:.2f}% | {affinity['max_zone_work_share_mean'] * 100:.2f}% | {affinity['busiest_zone_work_over_mean_mean']:.3f}x | {affinity['static_throughput_loss_vs_same_work_ideal_mean'] * 100:.2f}% |

Uniform hashing touches approximately
{uniform['physical_task_count_mean']:.0f} physical platters and nearly removes
owner-level work skew. Static ownership alone is therefore not a strong
bottleneck for this batch under well-dispersed placement.

When access affinity and physical ownership are correlated, logical demand is
highly concentrated. Batch-wide merge reduces that concentration substantially,
but does not remove it: the average post-merge busiest-owner work share remains
{affinity['max_zone_work_share_mean'] * 100:.2f}%, compared with the balanced
12.5%. Static ownership then retains
{affinity['static_capacity_efficiency_mean'] * 100:.2f}% of the same-work ideal
throughput on average. Across the 10 deterministic placement seeds, the
static throughput loss ranges from
{affinity['static_throughput_loss_vs_same_work_ideal_min'] * 100:.2f}% to
{affinity['static_throughput_loss_vs_same_work_ideal_max'] * 100:.2f}%.

## 圖表讀法

- Figure 1 只回答「static ownership 損失多少 throughput」。越低越好。
  每個 placement 都與它自己相同 merged work 的 ideal 比較。
- Figure 2 直接畫出 representative seed 的 8 個等面積 static zones。
  完全平衡時每個 zone 應承擔 12.5% work；提早完成的 cold zone
  無法協助仍然 busy 的 zone。

## 可支持的結論

這個 pilot 支持條件式主張：access skew 本身不足以證明 static zones
有問題；真正的風險是 access popularity 與 physical ownership
correlated。下一階段應在多個連續 batches 與不同 affinity width 下驗證
這個條件的發生頻率，而不是只展示單一最壞案例。
"""
    path.write_text(text, encoding="utf-8")


def _write_figures(
    result: AzureStaticZonePilotResult,
    figures_dir: Path,
    representative_seed: int,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch, Rectangle

    aggregates = {
        row["placement"]: row for row in result.aggregate_rows
    }
    labels = ["Well-dispersed\nplacement", "Owner-correlated\nplacement"]
    colors = ["#4C78A8", "#D65F5F"]
    placements = list(PLACEMENT_ORDER)

    losses = [
        aggregates[name][
            "static_throughput_loss_vs_same_work_ideal_mean"
        ]
        * 100
        for name in placements
    ]
    fig, axis = plt.subplots(figsize=(7.2, 4.4))
    bars = axis.bar(range(2), losses, color=colors, width=0.56)
    axis.set_xticks(range(2), labels)
    axis.set_ylim(0, max(losses) * 1.28)
    axis.set_ylabel("Throughput loss (%)")
    fig.suptitle(
        "Static zones lose throughput when work cannot cross boundaries",
        fontsize=15,
        y=0.98,
    )
    axis.set_title(
        "Lower is better; mean of 10 placement seeds",
        color="#555555",
        fontsize=9,
        pad=8,
    )
    axis.grid(axis="y", color="#DDDDDD", linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines[["top", "right"]].set_visible(False)
    for bar, value in zip(bars, losses):
        axis.text(
            bar.get_x() + bar.get_width() / 2,
            value + max(losses) * 0.035,
            f"{value:.1f}% loss",
            ha="center",
            va="bottom",
            fontsize=12,
            fontweight="bold",
        )
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    for suffix in ("png", "pdf"):
        fig.savefig(
            figures_dir / f"fig1_skew_and_static_loss.{suffix}",
            dpi=220,
            bbox_inches="tight",
        )
    plt.close(fig)

    selected = [
        row
        for row in result.zone_rows
        if int(row["seed"]) == representative_seed
    ]
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 5.0))
    panel_titles = ["Well-dispersed placement", "Owner-correlated placement"]
    for axis, placement, title in zip(
        axes,
        placements,
        panel_titles,
    ):
        rows = sorted(
            (row for row in selected if row["placement"] == placement),
            key=lambda row: int(row["zone_id"]),
        )
        shares = [float(row["work_share"]) * 100 for row in rows]
        for zone_id, share in enumerate(shares):
            column = 0 if zone_id < 4 else 1
            row = zone_id if zone_id < 4 else zone_id - 4
            x = column * 1.14
            y = 3 - row
            if share > 13.5:
                fill = "#E88471"
            elif share < 8.0:
                fill = "#D5D5D5"
            else:
                fill = "#B9D2E8"
            axis.add_patch(
                Rectangle(
                    (x, y),
                    1.0,
                    0.88,
                    facecolor=fill,
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
        axis.set_ylim(-0.32, 4.08)
        axis.set_aspect("equal")
        axis.axis("off")
        axis.set_title(title, fontsize=12, pad=8)

    axes[0].text(
        1.07,
        -0.25,
        "All zones carry about 12.5%",
        ha="center",
        va="top",
        fontsize=9,
        color="#444444",
    )
    axes[1].text(
        1.07,
        -0.25,
        "Cold zones finish early; busy zones remain",
        ha="center",
        va="top",
        fontsize=9,
        color="#444444",
    )
    fig.suptitle(
        "Equal-size static zones do not guarantee equal work",
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
        bbox_to_anchor=(0.5, 0.005),
    )
    fig.text(
        0.99,
        0.01,
        f"Post-merge work, example seed {representative_seed}",
        ha="right",
        fontsize=8,
        color="#666666",
    )
    fig.tight_layout(rect=(0, 0.10, 1, 0.93))
    for suffix in ("png", "pdf"):
        fig.savefig(
            figures_dir / f"fig2_zone_work_distribution.{suffix}",
            dpi=220,
            bbox_inches="tight",
        )
    plt.close(fig)


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


def _placement_label(placement: str) -> str:
    if placement == UNIFORM_HASH:
        return "Uniform object hash"
    if placement == APP_AFFINITY:
        return "Application owner affinity"
    raise ValueError(f"unsupported placement: {placement}")


def _top_application_share(accesses: list[AzureBatchAccess]) -> float:
    counts: dict[str, int] = {}
    for access in accesses:
        counts[access.application] = counts.get(access.application, 0) + 1
    return max(counts.values()) / len(accesses)


def _hash_u64(seed: int, *parts: str) -> int:
    payload = f"{seed}|" + "|".join(parts)
    return int.from_bytes(
        hashlib.blake2b(payload.encode("utf-8"), digest_size=8).digest(),
        "big",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_path(value: str, root: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()
