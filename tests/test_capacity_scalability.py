from __future__ import annotations

from pathlib import Path
import unittest

from glass_sim.capacity_scalability import (
    FIXED_FOOTPRINT,
    GROWING_FOOTPRINT,
    CapacityGeometryConfig,
    CapacityScalabilityConfig,
    CapacityWorkloadConfig,
    run_capacity_scalability,
)
from glass_sim.panel_static_zone import (
    PanelMovementConfig,
    PanelTimingConfig,
)


def _config() -> CapacityScalabilityConfig:
    return CapacityScalabilityConfig(
        output_dir=Path("results/test-capacity-scalability"),
        seeds=(71, 72),
        storage_rack_counts=(1, 2, 4),
        reader_count=8,
        shuttle_count=8,
        geometry=CapacityGeometryConfig(
            levels=8,
            zone_height_racks=2,
            rack_length_m=2.0,
            slots_per_half_per_rack=32,
            fixed_footprint_half_length_m=2.0,
            glass_capacity_bytes=7_000_000_000_000,
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
        workload=CapacityWorkloadConfig(
            task_count=64,
            request_size_bytes=64 * 1024**2,
        ),
    )


class CapacityScalabilityTests(unittest.TestCase):
    def test_capacity_growth_preserves_work_and_active_resources(self) -> None:
        result = run_capacity_scalability(_config())

        self.assertTrue(result.validation["passed"])
        self.assertEqual(result.validation["checked_runs"], 12)
        for row in result.aggregate_rows:
            self.assertEqual(row["physical_task_count_mean"], 64)
            self.assertEqual(row["logical_request_count_mean"], 64)
            self.assertEqual(row["reader_count_mean"], 8)
            self.assertEqual(row["shuttle_count_mean"], 8)

    def test_fixed_footprint_is_stable_but_growing_footprint_degrades(self) -> None:
        result = run_capacity_scalability(_config())
        control = sorted(
            [
                row
                for row in result.aggregate_rows
                if row["scenario"] == FIXED_FOOTPRINT
            ],
            key=lambda row: row["storage_rack_count"],
        )
        growing = sorted(
            [
                row
                for row in result.aggregate_rows
                if row["scenario"] == GROWING_FOOTPRINT
            ],
            key=lambda row: row["storage_rack_count"],
        )

        self.assertAlmostEqual(
            control[0]["normalized_throughput_mean"],
            control[-1]["normalized_throughput_mean"],
            delta=0.02,
        )
        self.assertLess(
            growing[-1]["normalized_throughput_mean"],
            growing[0]["normalized_throughput_mean"],
        )
        movement = [row["avg_shuttle_movement_s_mean"] for row in growing]
        self.assertEqual(movement, sorted(movement))

    def test_platter_slots_and_length_scale_as_configured(self) -> None:
        result = run_capacity_scalability(_config())
        growing = sorted(
            [
                row
                for row in result.aggregate_rows
                if row["scenario"] == GROWING_FOOTPRINT
            ],
            key=lambda row: row["storage_rack_count"],
        )

        self.assertEqual(
            [row["platter_slot_count_mean"] for row in growing],
            [512, 1024, 2048],
        )
        self.assertEqual(
            [row["half_panel_length_m_mean"] for row in growing],
            [2.0, 4.0, 8.0],
        )

    def test_time_breakdown_is_conserved_and_only_movement_grows(self) -> None:
        result = run_capacity_scalability(_config())
        growing = sorted(
            [
                row
                for row in result.aggregate_rows
                if row["scenario"] == GROWING_FOOTPRINT
            ],
            key=lambda row: row["storage_rack_count"],
        )

        for row in growing:
            self.assertAlmostEqual(
                row["avg_cycle_s_mean"],
                row["avg_shuttle_movement_s_mean"]
                + row["avg_reader_read_s_mean"]
                + row["avg_reader_load_unload_s_mean"]
                + row["avg_storage_handling_s_mean"],
            )
        self.assertEqual(
            len({row["avg_reader_service_s_mean"] for row in growing}),
            1,
        )
        self.assertEqual(
            len({row["avg_reader_read_s_mean"] for row in growing}),
            1,
        )
        self.assertEqual(
            len(
                {
                    row["avg_reader_load_unload_s_mean"]
                    for row in growing
                }
            ),
            1,
        )
        self.assertEqual(
            len({row["avg_storage_handling_s_mean"] for row in growing}),
            1,
        )
        self.assertGreater(
            growing[0]["reader_service_time_share_mean"],
            growing[-1]["reader_service_time_share_mean"],
        )


if __name__ == "__main__":
    unittest.main()
