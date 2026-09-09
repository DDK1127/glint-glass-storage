from __future__ import annotations

import csv
import gzip
import hashlib
import io
from pathlib import Path
import tempfile
import unittest

from glass_sim.azure_blob_preprocess import OUTPUT_COLUMNS
from glass_sim.azure_static_zone_pilot import (
    APP_AFFINITY,
    UNIFORM_HASH,
    AzureStaticZonePilotConfig,
    run_azure_static_zone_pilot,
)
from glass_sim.panel_static_zone import (
    PanelGeometryConfig,
    PanelMovementConfig,
    PanelTimingConfig,
)


class AzureStaticZonePilotTests(unittest.TestCase):
    def test_pilot_preserves_trace_and_is_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root / "batch.csv.gz"
            self._write_batch(batch)
            config = self._config(root, batch)

            first = run_azure_static_zone_pilot(config)
            second = run_azure_static_zone_pilot(config)

        self.assertTrue(first.validation["passed"])
        self.assertEqual(first.run_rows, second.run_rows)
        self.assertEqual(
            {row["placement"] for row in first.run_rows},
            {UNIFORM_HASH, APP_AFFINITY},
        )
        self.assertTrue(
            all(row["logical_request_count"] == 16 for row in first.run_rows)
        )
        self.assertTrue(
            all(row["physical_unique_bytes"] == 100 for row in first.run_rows)
        )
        self.assertTrue(
            all(row["zone_count"] == 8 for row in first.run_rows)
        )

    @staticmethod
    def _config(
        root: Path,
        batch: Path,
    ) -> AzureStaticZonePilotConfig:
        return AzureStaticZonePilotConfig(
            output_dir=root / "results",
            batch_path=batch,
            expected_batch_sha256=hashlib.sha256(
                batch.read_bytes()
            ).hexdigest(),
            seeds=(11, 12),
            geometry=PanelGeometryConfig(
                levels=8,
                zone_height_racks=2,
                half_panel_length_m=16.0,
                slots_per_half=4,
                glass_capacity_bytes=8 * 1024**3,
            ),
            movement=PanelMovementConfig(
                horizontal_max_m_s=2.0,
                horizontal_accel_m_s2=2.0,
                horizontal_min_s=1.0,
                vertical_s_per_level=3.0,
            ),
            timing=PanelTimingConfig(
                storage_pick_s=3.0,
                reader_load_s=3.0,
                reader_unload_s=3.0,
                storage_place_s=3.0,
                reader_mount_s=1.0,
                reader_base_s=0.00035,
                reader_mib_per_s=60.0,
            ),
        )

    @staticmethod
    def _write_batch(path: Path) -> None:
        rows = []
        for index in range(16):
            object_index = index % 10
            rows.append(
                [
                    str(1000 + index),
                    str(index),
                    str(index + 1),
                    "r",
                    "u",
                    "hot-app" if index < 12 else "cold-app",
                    f"i{index}",
                    f"b{object_index}",
                    f"e{object_index}",
                    "type",
                    "10",
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
