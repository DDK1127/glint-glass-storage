from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ArchitectureConfig:
    rows: int
    columns: int
    rows_per_zone: int
    reader_count: int
    feeder_buffer_slots: int
    glass_capacity_bytes: int

    def validate(self) -> None:
        if self.rows <= 0 or self.columns <= 0:
            raise ValueError("rows and columns must be positive")
        if self.rows_per_zone <= 0:
            raise ValueError("rows_per_zone must be positive")
        if self.rows % self.rows_per_zone != 0:
            raise ValueError("rows must be divisible by rows_per_zone")
        if self.reader_count <= 0:
            raise ValueError("reader_count must be positive")
        if self.feeder_buffer_slots < 0:
            raise ValueError("feeder_buffer_slots cannot be negative")
        if self.glass_capacity_bytes <= 0:
            raise ValueError("glass_capacity_bytes must be positive")


@dataclass(frozen=True)
class TimingConfig:
    zone_pick_s: float
    zone_place_s: float
    horizontal_slot_s: float
    return_pick_s: float
    return_place_s: float
    reader_fixed_s: float
    reader_mib_per_s: float

    def validate(self) -> None:
        values = asdict(self)
        for key, value in values.items():
            if value < 0:
                raise ValueError(f"{key} cannot be negative")
        if self.reader_mib_per_s <= 0:
            raise ValueError("reader_mib_per_s must be positive")


@dataclass(frozen=True)
class SimulationConfig:
    trace_path: Path
    output_dir: Path
    max_requests: int | None
    architecture: ArchitectureConfig
    timing: TimingConfig

    def validate(self) -> None:
        if not self.trace_path.exists():
            raise FileNotFoundError(f"trace_path does not exist: {self.trace_path}")
        if self.max_requests is not None and self.max_requests <= 0:
            raise ValueError("max_requests must be positive when set")
        self.architecture.validate()
        self.timing.validate()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "trace_path": str(self.trace_path),
            "output_dir": str(self.output_dir),
            "max_requests": self.max_requests,
            "architecture": asdict(self.architecture),
            "timing": asdict(self.timing),
        }


def load_config(path: str | Path) -> SimulationConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    base_dir = config_path.parent.parent if config_path.parent.name == "configs" else Path.cwd()
    trace_path = _resolve_path(raw["trace_path"], base_dir)
    output_dir = _resolve_path(raw["output_dir"], base_dir)

    config = SimulationConfig(
        trace_path=trace_path,
        output_dir=output_dir,
        max_requests=raw.get("max_requests"),
        architecture=ArchitectureConfig(**raw["architecture"]),
        timing=TimingConfig(**raw["timing"]),
    )
    config.validate()
    return config


def with_overrides(
    config: SimulationConfig,
    *,
    trace_path: str | None = None,
    output_dir: str | None = None,
    max_requests: int | None = None,
) -> SimulationConfig:
    updated = SimulationConfig(
        trace_path=Path(trace_path) if trace_path else config.trace_path,
        output_dir=Path(output_dir) if output_dir else config.output_dir,
        max_requests=max_requests if max_requests is not None else config.max_requests,
        architecture=config.architecture,
        timing=config.timing,
    )
    updated.validate()
    return updated


def _resolve_path(value: str, base_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()
