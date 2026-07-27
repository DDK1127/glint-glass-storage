from __future__ import annotations

from dataclasses import asdict, dataclass
import bz2
from contextlib import contextmanager
import csv
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Iterator, TextIO

from .paths import portable_path, repository_root_for_config


REQUIRED_COLUMNS = {
    "Timestamp",
    "AnonRegion",
    "AnonUserId",
    "AnonAppName",
    "AnonFunctionInvocationId",
    "AnonBlobName",
    "BlobType",
    "AnonBlobETag",
    "BlobBytes",
    "Read",
    "Write",
}

OUTPUT_COLUMNS = (
    "TimestampMs",
    "ArrivalMs",
    "SourceRow",
    "AnonRegion",
    "AnonUserId",
    "AnonAppName",
    "AnonFunctionInvocationId",
    "AnonBlobName",
    "AnonBlobETag",
    "BlobType",
    "BlobBytes",
)


@dataclass(frozen=True)
class AzureBlobPreprocessConfig:
    input_path: Path
    output_path: Path
    sample_output_path: Path
    manifest_path: Path
    temp_dir: Path
    expected_source_sha256: str
    sample_read_requests: int
    sort_buffer: str
    max_input_rows: int | None

    def validate(self) -> None:
        if not self.input_path.is_file():
            raise ValueError(f"input trace does not exist: {self.input_path}")
        if len(self.expected_source_sha256) != 64:
            raise ValueError("expected_source_sha256 must contain 64 hexadecimal characters")
        try:
            int(self.expected_source_sha256, 16)
        except ValueError as exc:
            raise ValueError("expected_source_sha256 must be hexadecimal") from exc
        if self.sample_read_requests <= 0:
            raise ValueError("sample_read_requests must be positive")
        if not self.sort_buffer:
            raise ValueError("sort_buffer cannot be empty")
        if self.max_input_rows is not None and self.max_input_rows <= 0:
            raise ValueError("max_input_rows must be positive or null")
        output_paths = {
            self.output_path.resolve(),
            self.sample_output_path.resolve(),
            self.manifest_path.resolve(),
        }
        if len(output_paths) != 3:
            raise ValueError("output, sample, and manifest paths must be distinct")

    def to_json_dict(self) -> dict[str, Any]:
        values = asdict(self)
        for key in ("input_path", "output_path", "sample_output_path", "manifest_path", "temp_dir"):
            values[key] = portable_path(values[key])
        return values


def load_azure_blob_preprocess_config(
    path: str | Path,
) -> AzureBlobPreprocessConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    root = repository_root_for_config(config_path)
    config = AzureBlobPreprocessConfig(
        input_path=_resolve_path(raw["input_path"], root),
        output_path=_resolve_path(raw["output_path"], root),
        sample_output_path=_resolve_path(raw["sample_output_path"], root),
        manifest_path=_resolve_path(raw["manifest_path"], root),
        temp_dir=_resolve_path(raw["temp_dir"], root),
        expected_source_sha256=str(raw["expected_source_sha256"]).lower(),
        sample_read_requests=int(raw["sample_read_requests"]),
        sort_buffer=str(raw["sort_buffer"]),
        max_input_rows=(
            int(raw["max_input_rows"])
            if raw.get("max_input_rows") is not None
            else None
        ),
    )
    config.validate()
    return config


def preprocess_azure_blob_trace(
    config: AzureBlobPreprocessConfig,
) -> dict[str, Any]:
    config.validate()
    source_sha256 = _sha256(config.input_path)
    if source_sha256 != config.expected_source_sha256:
        raise ValueError(
            "source checksum mismatch: "
            f"expected {config.expected_source_sha256}, got {source_sha256}"
        )

    for path in (
        config.output_path,
        config.sample_output_path,
        config.manifest_path,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
    config.temp_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="azure-blob-preprocess-",
        dir=config.temp_dir,
    ) as directory:
        working_dir = Path(directory)
        sorted_intermediate = working_dir / "reads.sorted.tsv"
        source_stats = _normalize_and_sort(config, sorted_intermediate, working_dir)
        output_stats = _write_canonical_outputs(
            config,
            sorted_intermediate,
            working_dir,
        )

    validation = {
        "source_checksum_matches": True,
        "all_source_rows_classified": (
            source_stats["eligible_read_rows"]
            + source_stats["excluded_read_rows_missing_blob_bytes"]
            + source_stats["non_read_rows"]
            == source_stats["input_rows"]
        ),
        "all_read_rows_classified": (
            source_stats["eligible_read_rows"]
            + source_stats["excluded_read_rows_missing_blob_bytes"]
            == source_stats["read_rows"]
        ),
        "eligible_read_count_preserved": (
            source_stats["eligible_read_rows"] == output_stats["output_rows"]
        ),
        "output_is_timestamp_sorted": output_stats["timestamp_descents"] == 0,
        "stable_tie_order": output_stats["unstable_timestamp_ties"] == 0,
        "sample_is_prefix_of_canonical_output": output_stats[
            "sample_is_prefix_of_output"
        ],
    }
    validation["passed"] = all(validation.values())
    if not validation["passed"]:
        raise RuntimeError(f"preprocessing validation failed: {validation}")

    manifest = {
        "dataset": "Azure Functions Blob Access Trace 2020",
        "method": {
            "operation_filter": "Read == True and BlobBytes is present",
            "missing_blob_bytes": (
                "exclude and count; no zero-fill or statistical imputation"
            ),
            "sort_keys": ["TimestampMs", "SourceRow"],
            "deduplication": "none",
            "request_merge": "deferred to experiment batches after platter mapping",
            "platter_packing": "not performed",
            "owner_assignment": "not performed",
        },
        "config": config.to_json_dict(),
        "source": {
            "path": portable_path(config.input_path),
            "size_bytes": config.input_path.stat().st_size,
            "sha256": source_sha256,
        },
        "source_stats": source_stats,
        "output": {
            "path": portable_path(config.output_path),
            "size_bytes": config.output_path.stat().st_size,
            "sha256": _sha256(config.output_path),
            **output_stats,
        },
        "sample": {
            "path": portable_path(config.sample_output_path),
            "size_bytes": config.sample_output_path.stat().st_size,
            "sha256": _sha256(config.sample_output_path),
            "rows": min(
                config.sample_read_requests,
                output_stats["output_rows"],
            ),
        },
        "validation": validation,
    }
    _write_json_atomic(config.manifest_path, manifest)
    return manifest


def _normalize_and_sort(
    config: AzureBlobPreprocessConfig,
    sorted_intermediate: Path,
    working_dir: Path,
) -> dict[str, Any]:
    command = [
        "sort",
        "-t",
        "\t",
        "-k1,1n",
        "-k2,2n",
        "-S",
        config.sort_buffer,
        "-T",
        str(working_dir),
    ]
    environment = {**os.environ, "LC_ALL": "C"}
    stats: dict[str, Any] = {
        "input_rows": 0,
        "read_rows": 0,
        "eligible_read_rows": 0,
        "non_read_rows": 0,
        "write_rows": 0,
        "read_and_write_rows": 0,
        "neither_read_nor_write_rows": 0,
        "read_rows_missing_blob_name": 0,
        "read_rows_missing_etag": 0,
        "read_rows_missing_blob_bytes": 0,
        "excluded_read_rows_missing_blob_bytes": 0,
        "read_rows_zero_bytes": 0,
        "read_bytes": 0,
        "max_read_blob_bytes": 0,
        "source_order_timestamp_descents": 0,
        "min_read_timestamp_ms": None,
        "max_read_timestamp_ms": None,
    }
    previous_timestamp: int | None = None

    with sorted_intermediate.open("w", encoding="utf-8", newline="") as sorted_handle:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=sorted_handle,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=environment,
        )
        assert process.stdin is not None
        try:
            with bz2.open(config.input_path, "rt", encoding="utf-8", newline="") as source:
                reader = csv.DictReader(source)
                missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
                if missing:
                    raise ValueError(
                        f"Azure trace is missing required columns: {sorted(missing)}"
                    )
                for source_row, row in enumerate(reader, start=1):
                    if (
                        config.max_input_rows is not None
                        and source_row > config.max_input_rows
                    ):
                        break
                    timestamp_ms = _parse_nonnegative_int(
                        row["Timestamp"],
                        "Timestamp",
                        source_row,
                    )
                    is_read = _parse_bool(row["Read"], "Read", source_row)
                    is_write = _parse_bool(row["Write"], "Write", source_row)
                    stats["input_rows"] += 1
                    stats["write_rows"] += int(is_write)
                    stats["read_and_write_rows"] += int(is_read and is_write)
                    stats["neither_read_nor_write_rows"] += int(
                        not is_read and not is_write
                    )
                    if (
                        previous_timestamp is not None
                        and timestamp_ms < previous_timestamp
                    ):
                        stats["source_order_timestamp_descents"] += 1
                    previous_timestamp = timestamp_ms

                    if not is_read:
                        stats["non_read_rows"] += 1
                        continue

                    stats["read_rows"] += 1
                    stats["read_rows_missing_blob_name"] += int(
                        not row["AnonBlobName"]
                    )
                    stats["read_rows_missing_etag"] += int(
                        not row["AnonBlobETag"]
                    )
                    if not row["BlobBytes"].strip():
                        stats["read_rows_missing_blob_bytes"] += 1
                        stats["excluded_read_rows_missing_blob_bytes"] += 1
                        continue

                    blob_bytes = _parse_nonnegative_int(
                        row["BlobBytes"],
                        "BlobBytes",
                        source_row,
                    )
                    stats["eligible_read_rows"] += 1
                    stats["read_rows_zero_bytes"] += int(blob_bytes == 0)
                    stats["read_bytes"] += blob_bytes
                    stats["max_read_blob_bytes"] = max(
                        stats["max_read_blob_bytes"],
                        blob_bytes,
                    )
                    stats["min_read_timestamp_ms"] = _optional_min(
                        stats["min_read_timestamp_ms"],
                        timestamp_ms,
                    )
                    stats["max_read_timestamp_ms"] = _optional_max(
                        stats["max_read_timestamp_ms"],
                        timestamp_ms,
                    )

                    payload = [
                        row["AnonRegion"],
                        row["AnonUserId"],
                        row["AnonAppName"],
                        row["AnonFunctionInvocationId"],
                        row["AnonBlobName"],
                        row["AnonBlobETag"],
                        row["BlobType"],
                        blob_bytes,
                    ]
                    encoded = json.dumps(
                        payload,
                        ensure_ascii=True,
                        separators=(",", ":"),
                    )
                    process.stdin.write(
                        f"{timestamp_ms}\t{source_row}\t{encoded}\n"
                    )
            process.stdin.close()
            stderr = process.stderr.read() if process.stderr is not None else ""
            if process.stderr is not None:
                process.stderr.close()
            return_code = process.wait()
            if return_code != 0:
                raise RuntimeError(
                    f"external sort failed with exit code {return_code}: {stderr}"
                )
        except BaseException:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
            if process.stderr is not None:
                process.stderr.close()
            process.kill()
            process.wait()
            raise

    if stats["read_rows"] == 0:
        raise ValueError("Azure trace contains no read requests")
    return stats


def _write_canonical_outputs(
    config: AzureBlobPreprocessConfig,
    sorted_intermediate: Path,
    working_dir: Path,
) -> dict[str, Any]:
    output_temporary = working_dir / "canonical.csv.gz"
    sample_temporary = working_dir / "sample.csv.gz"
    output_rows = 0
    timestamp_descents = 0
    unstable_timestamp_ties = 0
    previous_timestamp: int | None = None
    previous_source_row: int | None = None
    first_timestamp: int | None = None

    with (
        _open_deterministic_gzip_text(output_temporary) as output_handle,
        _open_deterministic_gzip_text(sample_temporary) as sample_handle,
        sorted_intermediate.open("r", encoding="utf-8") as sorted_handle,
    ):
        output_writer = csv.writer(output_handle, lineterminator="\n")
        sample_writer = csv.writer(sample_handle, lineterminator="\n")
        output_writer.writerow(OUTPUT_COLUMNS)
        sample_writer.writerow(OUTPUT_COLUMNS)

        for line in sorted_handle:
            timestamp_text, source_row_text, payload_text = line.rstrip("\n").split(
                "\t",
                2,
            )
            timestamp_ms = int(timestamp_text)
            source_row = int(source_row_text)
            payload = json.loads(payload_text)
            if first_timestamp is None:
                first_timestamp = timestamp_ms
            if previous_timestamp is not None:
                timestamp_descents += int(timestamp_ms < previous_timestamp)
                unstable_timestamp_ties += int(
                    timestamp_ms == previous_timestamp
                    and previous_source_row is not None
                    and source_row < previous_source_row
                )

            row = [
                timestamp_ms,
                timestamp_ms - first_timestamp,
                source_row,
                *payload,
            ]
            output_writer.writerow(row)
            if output_rows < config.sample_read_requests:
                sample_writer.writerow(row)

            output_rows += 1
            previous_timestamp = timestamp_ms
            previous_source_row = source_row

    os.replace(output_temporary, config.output_path)
    os.replace(sample_temporary, config.sample_output_path)
    sample_signatures = _read_gzip_row_signatures(
        config.sample_output_path,
        config.sample_read_requests,
    )
    output_prefix_signatures = _read_gzip_row_signatures(
        config.output_path,
        config.sample_read_requests,
    )
    return {
        "output_rows": output_rows,
        "first_timestamp_ms": first_timestamp,
        "last_timestamp_ms": previous_timestamp,
        "trace_span_ms": (
            previous_timestamp - first_timestamp
            if first_timestamp is not None and previous_timestamp is not None
            else 0
        ),
        "timestamp_descents": timestamp_descents,
        "unstable_timestamp_ties": unstable_timestamp_ties,
        "sample_is_prefix_of_output": sample_signatures == output_prefix_signatures,
    }


def _parse_bool(value: str, field: str, source_row: int) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"invalid {field} at source row {source_row}: {value!r}")


def _parse_nonnegative_int(
    value: str,
    field: str,
    source_row: int,
) -> int:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(
            f"invalid {field} at source row {source_row}: {value!r}"
        ) from exc
    integral = parsed.to_integral_value()
    if parsed != integral or integral < 0:
        raise ValueError(
            f"{field} must be a nonnegative integer at source row "
            f"{source_row}: {value!r}"
        )
    return int(integral)


def _optional_min(current: int | None, candidate: int) -> int:
    return candidate if current is None else min(current, candidate)


def _optional_max(current: int | None, candidate: int) -> int:
    return candidate if current is None else max(current, candidate)


def _row_signature(row: list[Any]) -> str:
    payload = json.dumps(row, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_gzip_row_signatures(path: Path, limit: int) -> list[str]:
    signatures: list[str] = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if tuple(header or ()) != OUTPUT_COLUMNS:
            raise ValueError(f"unexpected canonical trace header in {path}")
        for row in reader:
            if len(signatures) >= limit:
                break
            signatures.append(_row_signature(row))
    return signatures


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
    path.parent.mkdir(parents=True, exist_ok=True)
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
