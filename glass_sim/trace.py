from __future__ import annotations

from dataclasses import dataclass
import csv
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class TraceRequest:
    index: int
    arrival_s: float
    io_type: str
    lun: int
    offset: int
    size_bytes: int
    observed_response_s: float | None


def iter_trace(path: Path, max_requests: int | None = None) -> Iterator[TraceRequest]:
    first_timestamp: float | None = None
    emitted = 0

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"Timestamp", "IOType", "LUN", "Offset", "Size"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"trace is missing required columns: {sorted(missing)}")

        for raw_index, row in enumerate(reader):
            if max_requests is not None and emitted >= max_requests:
                break
            try:
                timestamp = float(row["Timestamp"])
                if first_timestamp is None:
                    first_timestamp = timestamp
                response = _optional_float(row.get("Response", ""))
                yield TraceRequest(
                    index=raw_index,
                    arrival_s=timestamp - first_timestamp,
                    io_type=row["IOType"].strip().upper(),
                    lun=int(row["LUN"]),
                    offset=int(row["Offset"]),
                    size_bytes=int(row["Size"]),
                    observed_response_s=response,
                )
                emitted += 1
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid trace row {raw_index + 2}: {row}") from exc


def _optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
