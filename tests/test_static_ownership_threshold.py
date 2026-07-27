from __future__ import annotations

from pathlib import Path
import unittest

from glass_sim.panel_static_zone import (
    PanelGeometryConfig,
    PanelMovementConfig,
    PanelTimingConfig,
)
from glass_sim.static_ownership_threshold import (
    StaticOwnershipThresholdConfig,
    StaticOwnershipThresholdWorkloadConfig,
    owner_counts_for_hot_task_count,
    run_static_ownership_threshold,
)


def _config() -> StaticOwnershipThresholdConfig:
    return StaticOwnershipThresholdConfig(
        output_dir=Path("results/test-static-ownership-threshold"),
        seeds=(41, 42),
        geometry=PanelGeometryConfig(
            levels=8,
            zone_height_racks=2,
            half_panel_length_m=16.0,
            slots_per_half=400,
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
        workload=StaticOwnershipThresholdWorkloadConfig(
            task_count=640,
            logical_request_count=10_000,
            request_size_bytes=64 * 1024**2,
            hot_owner=0,
            hot_owner_task_counts=(80, 96, 112, 128, 160, 320),
        ),
    )


class StaticOwnershipThresholdTests(unittest.TestCase):
    def test_owner_counts_are_exact_and_cold_work_is_evenly_spread(self) -> None:
        counts = owner_counts_for_hot_task_count(
            task_count=640,
            zone_count=8,
            hot_owner=0,
            hot_task_count=112,
        )

        self.assertEqual(counts[0], 112)
        self.assertEqual(sum(counts), 640)
        self.assertLessEqual(max(counts[1:]) - min(counts[1:]), 1)

    def test_study_preserves_work_and_finds_monotonic_loss(self) -> None:
        result = run_static_ownership_threshold(_config())

        self.assertTrue(result.validation["passed"])
        self.assertEqual(result.validation["checked_runs"], 12)
        throughput = [
            row["normalized_throughput_mean"]
            for row in result.aggregate_rows
        ]
        stranded = [
            row["stranded_capacity_share_mean"]
            for row in result.aggregate_rows
        ]
        self.assertEqual(throughput, sorted(throughput, reverse=True))
        self.assertEqual(stranded, sorted(stranded))
        for row in result.aggregate_rows:
            self.assertEqual(row["logical_request_count_mean"], 10_000)
            self.assertEqual(row["physical_task_count_mean"], 640)
            self.assertEqual(row["shuttle_count_mean"], 8)
            self.assertEqual(row["reader_count_mean"], 8)

    def test_loss_crossings_are_observed_not_interpolated(self) -> None:
        result = run_static_ownership_threshold(_config())
        tested = {
            row["hot_owner_task_count"]
            for row in result.aggregate_rows
        }

        for crossing in result.findings["crossings"].values():
            if crossing is not None:
                self.assertIn(crossing["hot_owner_task_count"], tested)
        self.assertIn(
            result.findings["skew_impact_knee"]["hot_owner_task_count"],
            tested,
        )


if __name__ == "__main__":
    unittest.main()
