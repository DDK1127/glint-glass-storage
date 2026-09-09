from __future__ import annotations

import csv
import hashlib
from pathlib import Path
import tempfile
import unittest

from glass_sim.lun_address_static_zone import (
    LunAddressStaticZoneConfig,
    map_stripe_to_position,
    run_lun_address_static_zone,
)
from glass_sim.panel_static_zone import (
    PanelGeometryConfig,
    PanelMovementConfig,
    PanelTimingConfig,
)


class LunAddressStaticZoneTests(unittest.TestCase):
    def test_linear_mapping_is_fixed_monotonic_and_reaches_endpoints(self) -> None:
        positions = [
            map_stripe_to_position(stripe, 10, 17, 64)
            for stripe in range(10, 18)
        ]

        self.assertEqual(positions[0], 0)
        self.assertEqual(positions[-1], 63)
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(
            map_stripe_to_position(13, 10, 17, 64),
            map_stripe_to_position(13, 10, 17, 64),
        )

    def test_experiment_preserves_requests_and_fixed_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            batch = root / "batch.csv"
            self._write_trace(
                source,
                [(float(index), index * 100, 4096) for index in range(8)],
            )
            self._write_trace(
                batch,
                [
                    (0.0, 0, 4096),
                    (0.1, 0, 8192),
                    (0.2, 100, 4096),
                    (0.3, 700, 4096),
                ],
            )
            config = self._config(root, source, batch)
            result = run_lun_address_static_zone(config)

        self.assertTrue(result.validation["passed"])
        self.assertEqual(result.summary["logical_request_count"], 4)
        self.assertEqual(result.summary["logical_bytes"], 20480)
        self.assertEqual(result.summary["physical_task_count"], 3)
        self.assertEqual(len(result.boundary_rows), 8)
        self.assertEqual(result.boundary_rows[0]["start_stripe_id"], 0)
        self.assertEqual(result.boundary_rows[-1]["end_stripe_id"], 7)

    @staticmethod
    def _config(
        root: Path,
        source: Path,
        batch: Path,
    ) -> LunAddressStaticZoneConfig:
        return LunAddressStaticZoneConfig(
            output_dir=root / "results",
            source_trace_path=source,
            batch_trace_path=batch,
            expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            expected_batch_sha256=hashlib.sha256(batch.read_bytes()).hexdigest(),
            batch_request_limit=4,
            stripe_bytes=100,
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
    def _write_trace(
        path: Path,
        rows: list[tuple[float, int, int]],
    ) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(
                ["Timestamp", "Response", "IOType", "LUN", "Offset", "Size"]
            )
            for timestamp, offset, size in rows:
                writer.writerow([timestamp, "", "R", 0, offset, size])


if __name__ == "__main__":
    unittest.main()
