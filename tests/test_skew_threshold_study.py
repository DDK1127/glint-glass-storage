from __future__ import annotations

from pathlib import Path
import unittest

from glass_sim.panel_static_zone import (
    PanelGeometryConfig,
    PanelMovementConfig,
    PanelTimingConfig,
)
from glass_sim.skew_threshold_study import (
    SkewThresholdConfig,
    SkewThresholdWorkloadConfig,
    analyze_thresholds,
    run_skew_threshold_study,
)


def _config() -> SkewThresholdConfig:
    return SkewThresholdConfig(
        output_dir=Path("results/test-skew-threshold"),
        seeds=(11, 12),
        hot_zone_fractions=(0.125, 0.25, 0.8),
        throughput_loss_thresholds=(0.1, 0.2),
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
        workload=SkewThresholdWorkloadConfig(
            batch_size=160,
            request_size_bytes=64 * 1024**2,
            hot_zone=0,
        ),
    )


class SkewThresholdStudyTests(unittest.TestCase):
    def test_merge_conservation_and_balanced_normalization(self) -> None:
        result = run_skew_threshold_study(_config())

        self.assertTrue(result.validation["passed"])
        self.assertEqual(result.validation["checked_runs"], 6)
        for row in result.run_rows:
            self.assertEqual(row["logical_request_count"], 160)
            self.assertLessEqual(row["service_operation_count"], 160)
            if row["hot_zone_fraction_target"] == 0.125:
                self.assertAlmostEqual(row["throughput_vs_balanced"], 1.0)
                self.assertAlmostEqual(row["throughput_loss_fraction"], 0.0)

    def test_hot_request_share_is_exact(self) -> None:
        result = run_skew_threshold_study(_config())

        for row in result.run_rows:
            self.assertAlmostEqual(
                row["hot_zone_fraction_actual"],
                row["hot_zone_fraction_target"],
            )

    def test_threshold_analysis_uses_first_observed_crossing(self) -> None:
        rows = []
        for fraction, loss in [(0.125, 0.0), (0.25, 0.12), (0.5, 0.24)]:
            rows.append(
                {
                    "hot_zone_fraction_target": fraction,
                    "throughput_loss_fraction_mean": loss,
                    "hot_service_share_mean": fraction,
                    "hot_work_share_mean": fraction,
                    "throughput_req_per_s_mean": 1.0 - loss,
                    "throughput_vs_balanced_mean": 1.0 - loss,
                    "service_count_vs_balanced_mean": 1.0,
                    "stranded_capacity_share_mean": loss,
                }
            )

        findings = analyze_thresholds(_config(), rows)

        self.assertEqual(
            findings["threshold_crossings"]["0.100"]["request_skew"],
            0.25,
        )
        self.assertEqual(
            findings["threshold_crossings"]["0.200"]["request_skew"],
            0.5,
        )


if __name__ == "__main__":
    unittest.main()
