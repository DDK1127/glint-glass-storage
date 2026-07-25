from __future__ import annotations

from pathlib import Path
import unittest

from glass_sim.panel_static_zone import (
    PanelGeometryConfig,
    PanelMovementConfig,
    PanelStaticZoneConfig,
    PanelStaticZoneSimulator,
    PanelTimingConfig,
    PanelWorkloadConfig,
    merge_panel_requests,
)
from glass_sim.static_baseline_study import (
    exact_zone_assignment,
    generate_paired_active_tasks,
    generate_paired_requests,
)


def _config(batch_size: int = 16, request_merge: bool = False) -> PanelStaticZoneConfig:
    return PanelStaticZoneConfig(
        output_dir=Path("results/test-panel-static-zone"),
        seed=7,
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
        workload=PanelWorkloadConfig(
            batch_size=batch_size,
            request_size_bytes=64 * 1024**2,
            request_merge=request_merge,
        ),
    )


class PanelStaticZoneTests(unittest.TestCase):
    def test_shuttle_next_fetch_starts_at_previous_return_slot(self) -> None:
        simulator = PanelStaticZoneSimulator(_config(batch_size=2))
        first = simulator.make_request(0, zone_id=0, local_level=0, slot_in_half=200, size_bytes=64 * 1024**2)
        second = simulator.make_request(1, zone_id=0, local_level=0, slot_in_half=200, size_bytes=64 * 1024**2)

        result = simulator.run([first, second])

        self.assertEqual(result.details[1].shuttle_start_level, first.level)
        self.assertEqual(result.details[1].shuttle_start_slot_in_half, first.slot_in_half)
        self.assertEqual(result.details[1].move_to_glass_s, 0.0)

    def test_merge_preserves_logical_bytes_and_priority(self) -> None:
        simulator = PanelStaticZoneSimulator(_config(batch_size=2))
        requests = [
            simulator.make_request(0, 0, 0, 10, 64 * 1024**2),
            simulator.make_request(1, 0, 0, 10, 64 * 1024**2),
        ]

        merged = merge_panel_requests(requests)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].request_index, 0)
        self.assertEqual(merged[0].merged_request_count, 2)
        self.assertEqual(merged[0].size_bytes, 128 * 1024**2)

    def test_exact_zone_assignment_hits_target_counts(self) -> None:
        assignments = exact_zone_assignment(
            batch_size=10_000,
            zone_count=8,
            hot_zone=0,
            hot_zone_fraction=0.8,
            hotspot_width=1,
            seed=11,
        )

        self.assertEqual(len(assignments), 10_000)
        self.assertEqual(assignments.count(0), 8_000)
        self.assertEqual(sum(assignments.count(zone) for zone in range(1, 8)), 2_000)

    def test_local_coordinates_are_paired_across_skew_cases(self) -> None:
        simulator_a = PanelStaticZoneSimulator(_config(batch_size=100))
        simulator_b = PanelStaticZoneSimulator(_config(batch_size=100))
        uniform = generate_paired_requests(simulator_a, 100, 64 * 1024**2, 0, 0.125, 1, 19)
        skewed = generate_paired_requests(simulator_b, 100, 64 * 1024**2, 0, 0.8, 1, 19)

        uniform_local = [
            (request.level % simulator_a.geometry.zone_height_racks, request.slot_in_half)
            for request in uniform
        ]
        skewed_local = [
            (request.level % simulator_b.geometry.zone_height_racks, request.slot_in_half)
            for request in skewed
        ]

        self.assertEqual(uniform_local, skewed_local)

    def test_active_tasks_are_unique_and_paired_across_zone_counts(self) -> None:
        simulator_a = PanelStaticZoneSimulator(_config(batch_size=80, request_merge=True))
        simulator_b = PanelStaticZoneSimulator(_config(batch_size=80, request_merge=True))
        one_zone = generate_paired_active_tasks(simulator_a, 80, 64 * 1024**2, 0, 1, 19)
        eight_zones = generate_paired_active_tasks(simulator_b, 80, 64 * 1024**2, 0, 8, 19)

        self.assertEqual(
            [(request.level % 2, request.slot_in_half) for request in one_zone],
            [(request.level % 2, request.slot_in_half) for request in eight_zones],
        )
        self.assertEqual(len({request.platter_id for request in one_zone}), 80)
        self.assertEqual(len({request.platter_id for request in eight_zones}), 80)
        self.assertEqual({request.zone_id for request in one_zone}, {0})
        self.assertEqual({request.zone_id for request in eight_zones}, set(range(8)))

    def test_timeline_and_capacity_metrics_are_valid(self) -> None:
        simulator = PanelStaticZoneSimulator(_config(batch_size=32))
        requests = simulator.generate_requests()
        result = simulator.run(requests)

        for detail in result.details:
            self.assertLessEqual(detail.arrival_s, detail.fetch_start_s)
            self.assertLessEqual(detail.fetch_start_s, detail.drive_done_s)
            self.assertLessEqual(detail.drive_done_s, detail.return_done_s)
        self.assertGreater(result.summary["static_capacity_efficiency"], 0.0)
        self.assertLessEqual(result.summary["static_capacity_efficiency"], 1.0)
        self.assertAlmostEqual(
            result.summary["static_capacity_efficiency"] + result.summary["stranded_capacity_share"],
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
