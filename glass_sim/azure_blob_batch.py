from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Iterator, TextIO

from .azure_blob_preprocess import OUTPUT_COLUMNS
from .paths import portable_path, repository_root_for_config
from .trace import iter_trace


@dataclass(frozen=True)
class AzureBlobBatchConfig:
    input_path: Path
    output_path: Path
    manifest_path: Path
    reference_lun_trace_path: Path
    expected_source_sha256: str
    start_read_index: int
    request_count: int

    def validate(self) -> None:
        if not self.input_path.is_file():
            raise ValueError(f"canonical Azure trace does not exist: {self.input_path}")
        if not self.reference_lun_trace_path.is_file():
            raise ValueError(
                f"reference LUN trace does not exist: {self.reference_lun_trace_path}"
            )
        if len(self.expected_source_sha256) != 64:
            raise ValueError("expected_source_sha256 must contain 64 hexadecimal characters")
        try:
            int(self.expected_source_sha256, 16)
        except ValueError as exc:
            raise ValueError("expected_source_sha256 must be hexadecimal") from exc
        if self.start_read_index < 0:
            raise ValueError("start_read_index cannot be negative")
        if self.request_count <= 0:
            raise ValueError("request_count must be positive")
        if self.output_path.resolve() == self.manifest_path.resolve():
            raise ValueError("output_path and manifest_path must be distinct")

    def to_json_dict(self) -> dict[str, Any]:
        values = asdict(self)
        for key in (
            "input_path",
            "output_path",
            "manifest_path",
            "reference_lun_trace_path",
        ):
            values[key] = portable_path(values[key])
        return values


def load_azure_blob_batch_config(path: str | Path) -> AzureBlobBatchConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    root = repository_root_for_config(config_path)
    config = AzureBlobBatchConfig(
        input_path=_resolve_path(raw["input_path"], root),
        output_path=_resolve_path(raw["output_path"], root),
        manifest_path=_resolve_path(raw["manifest_path"], root),
        reference_lun_trace_path=_resolve_path(
            raw["reference_lun_trace_path"],
            root,
        ),
        expected_source_sha256=str(raw["expected_source_sha256"]).lower(),
        start_read_index=int(raw["start_read_index"]),
        request_count=int(raw["request_count"]),
    )
    config.validate()
    return config


def extract_azure_blob_batch(config: AzureBlobBatchConfig) -> dict[str, Any]:
    config.validate()
    source_sha256 = _sha256(config.input_path)
    if source_sha256 != config.expected_source_sha256:
        raise ValueError(
            "canonical source checksum mismatch: "
            f"expected {config.expected_source_sha256}, got {source_sha256}"
        )

    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    config.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "wb",
        dir=config.output_path.parent,
        prefix=f".{config.output_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary_handle:
        temporary_output = Path(temporary_handle.name)

    try:
        batch_stats = _extract_rows(config, temporary_output)
        os.replace(temporary_output, config.output_path)
    except BaseException:
        temporary_output.unlink(missing_ok=True)
        raise

    reference_stats = _profile_reference_lun_batch(
        config.reference_lun_trace_path
    )
    manifest = {
        "dataset": "Azure Functions Blob Access Trace 2020",
        "selection": {
            "type": "consecutive_request_count",
            "start_read_index_zero_based": config.start_read_index,
            "request_count": config.request_count,
            "policy": (
                "earliest timestamp-sorted eligible reads; no hotspot, "
                "region, application, or peak-rate selection"
            ),
        },
        "config": config.to_json_dict(),
        "source": {
            "path": portable_path(config.input_path),
            "sha256": source_sha256,
        },
        "batch": {
            "path": portable_path(config.output_path),
            "size_bytes": config.output_path.stat().st_size,
            "sha256": _sha256(config.output_path),
            **batch_stats,
        },
        "reference_lun0_head_100k": reference_stats,
        "comparison_notes": [
            "Both artifacts use the first 100,000 timestamp-sorted reads.",
            "Their natural time spans are retained and are not rate-normalized.",
            "Azure blob-version identity and LUN offset identity are not equivalent.",
            "No object-to-platter packing or batch-wide platter merge is applied here.",
        ],
        "validation": {
            "source_checksum_matches": True,
            "requested_row_count_extracted": (
                batch_stats["request_count"] == config.request_count
            ),
            "timestamps_monotonic": batch_stats["timestamp_descents"] == 0,
            "batch_arrival_rebased_to_zero": (
                batch_stats["first_arrival_ms"] == 0
            ),
            "reference_request_count_matches": (
                reference_stats["read_request_count"] == config.request_count
            ),
        },
    }
    manifest["validation"]["passed"] = all(
        manifest["validation"].values()
    )
    if not manifest["validation"]["passed"]:
        raise RuntimeError(f"batch validation failed: {manifest['validation']}")
    _write_json_atomic(config.manifest_path, manifest)
    return manifest


def _extract_rows(
    config: AzureBlobBatchConfig,
    temporary_output: Path,
) -> dict[str, Any]:
    request_count = 0
    first_timestamp_ms: int | None = None
    last_timestamp_ms: int | None = None
    previous_timestamp_ms: int | None = None
    timestamp_descents = 0
    total_bytes = 0
    zero_byte_reads = 0
    blob_names: set[str] = set()
    blob_versions: set[tuple[str, str]] = set()
    application_names: set[str] = set()
    region_counts: dict[str, int] = {}
    sizes: list[int] = []

    with (
        gzip.open(config.input_path, "rt", encoding="utf-8", newline="") as source,
        _open_deterministic_gzip_text(temporary_output) as output,
    ):
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != OUTPUT_COLUMNS:
            raise ValueError("canonical Azure trace has an unexpected schema")
        writer = csv.DictWriter(
            output,
            fieldnames=OUTPUT_COLUMNS,
            lineterminator="\n",
        )
        writer.writeheader()

        end_index = config.start_read_index + config.request_count
        for read_index, row in enumerate(reader):
            if read_index < config.start_read_index:
                continue
            if read_index >= end_index:
                break
            timestamp_ms = int(row["TimestampMs"])
            if first_timestamp_ms is None:
                first_timestamp_ms = timestamp_ms
            if (
                previous_timestamp_ms is not None
                and timestamp_ms < previous_timestamp_ms
            ):
                timestamp_descents += 1
            row["ArrivalMs"] = str(timestamp_ms - first_timestamp_ms)
            writer.writerow(row)

            blob_bytes = int(row["BlobBytes"])
            request_count += 1
            total_bytes += blob_bytes
            zero_byte_reads += int(blob_bytes == 0)
            sizes.append(blob_bytes)
            blob_names.add(row["AnonBlobName"])
            blob_versions.add(
                (row["AnonBlobName"], row["AnonBlobETag"])
            )
            application_names.add(row["AnonAppName"])
            region = row["AnonRegion"]
            region_counts[region] = region_counts.get(region, 0) + 1
            previous_timestamp_ms = timestamp_ms
            last_timestamp_ms = timestamp_ms

    if request_count != config.request_count:
        raise ValueError(
            f"requested {config.request_count} rows at index "
            f"{config.start_read_index}, found {request_count}"
        )

    sizes.sort()
    unique_version_count = len(blob_versions)
    return {
        "request_count": request_count,
        "first_timestamp_ms": first_timestamp_ms,
        "last_timestamp_ms": last_timestamp_ms,
        "first_timestamp_utc": _timestamp_utc(first_timestamp_ms),
        "last_timestamp_utc": _timestamp_utc(last_timestamp_ms),
        "first_arrival_ms": 0,
        "span_ms": (
            last_timestamp_ms - first_timestamp_ms
            if first_timestamp_ms is not None and last_timestamp_ms is not None
            else 0
        ),
        "timestamp_descents": timestamp_descents,
        "logical_bytes": total_bytes,
        "zero_byte_reads": zero_byte_reads,
        "unique_blob_names": len(blob_names),
        "unique_blob_versions": unique_version_count,
        "repeated_blob_version_requests": request_count - unique_version_count,
        "repeated_blob_version_fraction": (
            1 - unique_version_count / request_count
        ),
        "unique_applications": len(application_names),
        "region_counts": dict(sorted(region_counts.items())),
        "blob_bytes_p50": _quantile(sizes, 0.50),
        "blob_bytes_p90": _quantile(sizes, 0.90),
        "blob_bytes_p99": _quantile(sizes, 0.99),
        "blob_bytes_max": sizes[-1],
    }


def _profile_reference_lun_batch(path: Path) -> dict[str, Any]:
    requests = [
        request for request in iter_trace(path) if request.io_type == "R"
    ]
    requests.sort(key=lambda request: (request.arrival_s, request.index))
    if not requests:
        raise ValueError("reference LUN trace contains no reads")
    unique_offsets = {(request.lun, request.offset) for request in requests}
    return {
        "path": portable_path(path),
        "read_request_count": len(requests),
        "span_s": requests[-1].arrival_s - requests[0].arrival_s,
        "logical_bytes": sum(request.size_bytes for request in requests),
        "unique_lun_offsets": len(unique_offsets),
        "repeated_lun_offset_fraction": 1 - len(unique_offsets) / len(requests),
    }


def _quantile(sorted_values: list[int], quantile: float) -> int:
    index = min(
        len(sorted_values) - 1,
        max(0, math.ceil(quantile * len(sorted_values)) - 1),
    )
    return sorted_values[index]


def _timestamp_utc(timestamp_ms: int | None) -> str | None:
    if timestamp_ms is None:
        return None
    return datetime.fromtimestamp(
        timestamp_ms / 1000,
        tz=timezone.utc,
    ).isoformat()


@contextmanager
def _open_deterministic_gzip_text(path: Path) -> Iterator[TextIO]:
    with path.open("wb") as raw_handle:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_handle,
            compresslevel=6,
            mtime=0,
        ) as compressed_handle:
            with io.TextIOWrapper(
                compressed_handle,
                encoding="utf-8",
                newline="",
            ) as text_handle:
                yield text_handle


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, indent=2)
        handle.write("\n")
    os.replace(temporary, path)


def _resolve_path(value: str, base_dir: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()
