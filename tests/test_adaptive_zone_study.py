from __future__ import annotations

from pathlib import Path
import unittest

from glass_sim.adaptive_zone_study import (
    AdaptiveZoneStudyConfig,
    AdaptiveZoneWorkloadConfig,
    PanelAdaptiveZoneSimulator,
    build_layout,
    enumerate_zone_heights,
    optimize_layout,
    run_adaptive_zone_study,
    static_layout,
    validate_layout,
)
from glass_sim.panel_static_zone import (
    PanelGeometryConfig,
    PanelMovementConfig,
    PanelStaticZoneConfig,
    PanelStaticZoneSimulator,
    PanelTimingConfig,
    PanelWorkloadConfig,
    merge_panel_requests,
)
from glass_sim.static_baseline_study import generate_paired_requests


def _config() -> AdaptiveZoneStudyConfig:
    return AdaptiveZoneStudyConfig(
        output_dir=Path("results/test-adaptive-zone"),
        seeds=(41, 42),
        hot_zone_fractions=(0.125, 0.5, 0.8),
        geometry=PanelGeometryConfig(
            levels=8,
            zone_height_racks=2,
            half_panel_length_m=16.0,
            slots_per_half=40,
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
        workload=AdaptiveZoneWorkloadConfig(
            batch_size=160,
            request_size_bytes=64 * 1024**2,
            hot_zone=0,
        ),
    )


def _panel_config(config: AdaptiveZoneStudyConfig) -> PanelStaticZoneConfig:
    return PanelStaticZoneConfig(
        output_dir=config.output_dir,
        seed=config.seeds[0],
        geometry=config.geometry,
        movement=config.movement,
        timing=config.timing,
        workload=PanelWorkloadConfig(
            batch_size=config.workload.batch_size,
            request_size_bytes=config.workload.request_size_bytes,
            placement="spatial_skew",
            request_merge=True,
            hot_zone=0,
            hot_zone_fraction=0.8,
            hot_zone_width=1,
        ),
    )


class AdaptiveZoneStudyTests(unittest.TestCase):
    def test_enumerates_all_positive_four_zone_compositions(self) -> None:
        layouts = enumerate_zone_heights(8, 4)

        self.assertEqual(len(layouts), 35)
        self.assertIn((2, 2, 2, 2), layouts)
        self.assertTrue(all(sum(layout) == 8 and min(layout) >= 1 for layout in layouts))

    def test_layout_is_contiguous_and_reader_is_local(self) -> None:
        config = _config()
        layout = build_layout(config.geometry, (1, 1, 3, 3), (2, 2, 2, 2))

        validate_layout(layout, levels=8, zones_per_side=4)
        self.assertEqual(len(layout), 8)
        self.assertEqual(len({region.zone_id for region in layout}), 8)
        for region in layout:
            self.assertLessEqual(region.start_level, region.reader_level)
            self.assertLess(region.reader_level, region.end_level)

    def test_remap_preserves_physical_trace(self) -> None:
        config = _config()
        panel_config = _panel_config(config)
        static = PanelStaticZoneSimulator(panel_config)
        logical = generate_paired_requests(
            static,
            batch_size=config.workload.batch_size,
            request_size_bytes=config.workload.request_size_bytes,
            hot_zone=0,
            hot_zone_fraction=0.8,
            hotspot_width=1,
            seed=config.seeds[0],
        )
        merged = merge_panel_requests(logical)
        layout = build_layout(config.geometry, (1, 1, 3, 3), (2, 2, 2, 2))
        adaptive = PanelAdaptiveZoneSimulator(panel_config, layout)

        remapped = adaptive.remap_requests(merged)

        physical = lambda request: (
            request.request_index,
            request.platter_id,
            request.size_bytes,
            request.merged_request_count,
            request.side,
            request.level,
            request.slot_in_half,
        )
        self.assertEqual([physical(request) for request in merged], [physical(request) for request in remapped])
        self.assertEqual(sum(request.merged_request_count for request in remapped), 160)

    def test_optimizer_contains_and_never_loses_to_static_candidate(self) -> None:
        config = _config()
        panel_config = _panel_config(config)
        simulator = PanelStaticZoneSimulator(panel_config)
        logical = generate_paired_requests(
            simulator,
            batch_size=160,
            request_size_bytes=config.workload.request_size_bytes,
            hot_zone=0,
            hot_zone_fraction=0.8,
            hotspot_width=1,
            seed=config.seeds[0],
        )
        merged = merge_panel_requests(logical)

        layout, adaptive_score, static_score = optimize_layout(config, merged)

        validate_layout(layout, levels=8, zones_per_side=4)
        self.assertLessEqual(adaptive_score.objective(), static_score.objective())
        self.assertEqual(len(static_layout(config.geometry)), 8)

    def test_study_is_reproducible_and_keeps_resource_counts(self) -> None:
        first = run_adaptive_zone_study(_config())
        second = run_adaptive_zone_study(_config())

        self.assertEqual(first.run_rows, second.run_rows)
        self.assertTrue(first.validation["passed"])
        self.assertEqual(first.validation["checked_runs"], 6)
        for row in first.run_rows:
            self.assertEqual(row["logical_request_count"], 160)
            self.assertEqual(row["shuttle_count"], 8)
            self.assertEqual(row["reader_count"], 8)
            self.assertEqual(
                row["service_operation_count"],
                next(
                    candidate["service_operation_count"]
                    for candidate in second.run_rows
                    if candidate["seed"] == row["seed"]
                    and candidate["hot_zone_fraction_target"]
                    == row["hot_zone_fraction_target"]
                ),
            )


if __name__ == "__main__":
    unittest.main()
