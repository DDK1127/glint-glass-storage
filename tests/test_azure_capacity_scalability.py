from __future__ import annotations

import csv
import gzip
import hashlib
import io
from pathlib import Path
import tempfile
import unittest

from glass_sim.azure_blob_preprocess import OUTPUT_COLUMNS
from glass_sim.azure_capacity_scalability import (
    AzureCapacityScalabilityConfig,
    build_virtual_platter_work,
    run_azure_capacity_scalability,
)
from glass_sim.azure_static_zone_pilot import AzureBatchAccess
from glass_sim.capacity_scalability import CapacityGeometryConfig
from glass_sim.panel_static_zone import PanelMovementConfig, PanelTimingConfig


def _accesses() -> list[AzureBatchAccess]:
    accesses = []
    for index in range(32):
        accesses.append(
            AzureBatchAccess(
                index=index,
                blob_name=f"blob-{index % 24}",
                blob_etag="v1",
                application="app",
                size_bytes=(index % 24 + 1) * 100,
            )
        )
    return accesses


class AzureCapacityScalabilityTests(unittest.TestCase):
    def test_virtual_platter_merge_conserves_trace_work(self) -> None:
        accesses = _accesses()
        work = build_virtual_platter_work(accesses, 8, 17)

        self.assertEqual(len(work), 8)
        self.assertEqual(sum(item.logical_request_count for item in work), 32)
        self.assertEqual(
            sum(item.unique_blob_version_count for item in work), 24
        )
        self.assertEqual(
            sum(item.size_bytes for item in work),
            sum((index + 1) * 100 for index in range(24)),
        )

    def test_virtual_platter_mapping_is_seed_reproducible(self) -> None:
        accesses = _accesses()
        first = build_virtual_platter_work(accesses, 8, 91)
        second = build_virtual_platter_work(accesses, 8, 91)
        third = build_virtual_platter_work(accesses, 8, 92)

        self.assertEqual(first, second)
        self.assertNotEqual(first, third)

    def test_config_rejects_unbalanced_virtual_platters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root / "batch.csv.gz"
            self._write_batch(batch)
            config = self._config(root, batch, virtual_platter_count=65)

            with self.assertRaisesRegex(ValueError, "divide evenly"):
                config.validate()

    def test_smoke_config_runs_with_paired_controls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root / "batch.csv.gz"
            self._write_batch(batch)
            config = self._config(root, batch)
            result = run_azure_capacity_scalability(config)

        self.assertTrue(result.validation["passed"])
        self.assertEqual(len(result.run_rows), 12)
        for row in result.run_rows:
            self.assertEqual(row["logical_request_count"], 100)
            self.assertEqual(row["physical_task_count"], 16)
            self.assertEqual(row["reader_count"], 8)
            self.assertEqual(row["shuttle_count"], 8)

    @staticmethod
    def _config(
        root: Path,
        batch: Path,
        virtual_platter_count: int = 16,
    ) -> AzureCapacityScalabilityConfig:
        return AzureCapacityScalabilityConfig(
            output_dir=root / "results",
            batch_path=batch,
            expected_batch_sha256=hashlib.sha256(
                batch.read_bytes()
            ).hexdigest(),
            seeds=(11, 12),
            storage_rack_counts=(1, 2, 4),
            reader_count=8,
            shuttle_count=8,
            virtual_platter_count=virtual_platter_count,
            geometry=CapacityGeometryConfig(
                levels=8,
                zone_height_racks=2,
                rack_length_m=2.0,
                slots_per_half_per_rack=100,
                fixed_footprint_half_length_m=2.0,
                glass_capacity_bytes=7_000_000_000_000,
            ),
            movement=PanelMovementConfig(2.0, 2.0, 1.0, 3.0),
            timing=PanelTimingConfig(
                3.0,
                3.0,
                3.0,
                3.0,
                1.0,
                0.00035,
                60.0,
            ),
        )

    @staticmethod
    def _write_batch(path: Path) -> None:
        rows = []
        for index in range(100):
            object_index = index % 80
            rows.append(
                [
                    str(1000 + index),
                    str(index),
                    str(index + 1),
                    "r",
                    "u",
                    f"app-{index % 4}",
                    f"invocation-{index}",
                    f"blob-{object_index}",
                    "v1",
                    "BlockBlob/application/octet-stream",
                    str((object_index + 1) * 1024),
                ]
            )
        with path.open("wb") as raw:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=raw,
                mtime=0,
            ) as compressed:
                with io.TextIOWrapper(
                    compressed,
                    encoding="utf-8",
                    newline="",
                ) as handle:
                    writer = csv.writer(handle, lineterminator="\n")
                    writer.writerow(OUTPUT_COLUMNS)
                    writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
