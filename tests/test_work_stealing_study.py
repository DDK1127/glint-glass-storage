from __future__ import annotations

from pathlib import Path
import unittest

from glass_sim.panel_static_zone import (
    PanelGeometryConfig,
    PanelMovementConfig,
    PanelTimingConfig,
)
from glass_sim.work_stealing_study import (
    WorkStealingStudyConfig,
    exact_hotspot_counts,
    generate_tasks,
    simulate_one_helper,
    simulate_strict_static,
)


def _config(task_count: int = 640) -> WorkStealingStudyConfig:
    return WorkStealingStudyConfig(
        output_dir=Path("results/test-work-stealing-study"),
        seeds=(11,),
        hotspot_fractions=(0.125, 0.5, 0.8),
        strong_hotspot_fraction=0.8,
        task_count=task_count,
        request_size_bytes=64 * 1024**2,
        hot_zone=0,
        helper_zones=(1, 2, 4, 7),
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
    )


class WorkStealingStudyTests(unittest.TestCase):
    def test_hotspot_counts_are_exact(self) -> None:
        balanced = exact_hotspot_counts(640, 8, 0, 0.125)
        strong = exact_hotspot_counts(640, 8, 0, 0.8)

        self.assertEqual(list(balanced.values()), [80] * 8)
        self.assertEqual(strong[0], 512)
        self.assertEqual(sum(strong.values()), 640)
        self.assertLessEqual(max(strong[zone] for zone in range(1, 8)), 19)

    def test_generated_tasks_are_unique_and_use_physical_zone_locations(self) -> None:
        config = _config()
        tasks = generate_tasks(config, 0.8, seed=11)
        flattened = [task for zone_tasks in tasks.values() for task in zone_tasks]

        self.assertEqual(len(flattened), 640)
        self.assertEqual(len({task.task_id for task in flattened}), 640)
        self.assertEqual(
            len({(task.level, task.global_slot) for task in flattened}),
            640,
        )
        for zone, zone_tasks in tasks.items():
            for task in zone_tasks:
                self.assertEqual((task.level // 2) * 2 + (task.global_slot // 400), zone)

    def test_helper_steals_tasks_and_uses_its_own_zone(self) -> None:
        config = _config()
        tasks = generate_tasks(config, 0.8, seed=11)
        result = simulate_one_helper(config, tasks, helper_zone=2)
        stolen = [record for record in result.records if record.cross_zone]

        self.assertGreater(len(stolen), 0)
        self.assertTrue(all(record.owner_zone == 0 for record in stolen))
        self.assertTrue(all(record.worker_zone == 2 for record in stolen))
        self.assertGreater(result.summary["helper_home_to_hot_center_s"], 0.0)
        self.assertEqual(result.summary["helper_route_hops"], 1)

    def test_one_helper_reduces_strong_hotspot_makespan(self) -> None:
        config = _config()
        tasks = generate_tasks(config, 0.8, seed=11)
        strict = simulate_strict_static(config, tasks)
        helper = simulate_one_helper(config, tasks, helper_zone=2)

        self.assertLess(helper.summary["makespan_s"], strict.summary["makespan_s"])
        self.assertGreater(helper.summary["total_travel_s"], strict.summary["total_travel_s"])
        self.assertEqual(helper.summary["task_count"], strict.summary["task_count"])

    def test_far_helper_has_longer_nominal_route(self) -> None:
        config = _config(task_count=80)
        tasks = generate_tasks(config, 0.8, seed=11)
        near = simulate_one_helper(config, tasks, helper_zone=2)
        far = simulate_one_helper(config, tasks, helper_zone=7)

        self.assertLess(
            near.summary["helper_home_to_hot_center_s"],
            far.summary["helper_home_to_hot_center_s"],
        )
        self.assertLess(near.summary["helper_route_hops"], far.summary["helper_route_hops"])


if __name__ == "__main__":
    unittest.main()
