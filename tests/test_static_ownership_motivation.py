from __future__ import annotations

from collections import Counter
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
from glass_sim.static_ownership_motivation import (
    MERGED_MODE,
    StaticOwnershipMotivationConfig,
    StaticOwnershipWorkloadConfig,
    build_paired_unique_tasks,
    expand_logical_requests,
    reader_relative_signature,
    run_static_ownership_motivation,
)


OWNER_DISTRIBUTIONS = {
    "balanced": (80, 80, 80, 80, 80, 80, 80, 80),
    "moderate": (160, 69, 69, 69, 69, 68, 68, 68),
    "strong": (320, 46, 46, 46, 46, 46, 45, 45),
}


def _config(seeds: tuple[int, ...] = (31, 32)) -> StaticOwnershipMotivationConfig:
    return StaticOwnershipMotivationConfig(
        output_dir=Path("results/test-static-ownership-motivation"),
        seeds=seeds,
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
        workload=StaticOwnershipWorkloadConfig(
            task_count=640,
            logical_request_count=10_000,
            request_size_bytes=64 * 1024**2,
            owner_distributions=OWNER_DISTRIBUTIONS,
        ),
    )


def _simulator(config: StaticOwnershipMotivationConfig) -> PanelStaticZoneSimulator:
    return PanelStaticZoneSimulator(
        PanelStaticZoneConfig(
            output_dir=config.output_dir,
            seed=config.seeds[0],
            geometry=config.geometry,
            movement=config.movement,
            timing=config.timing,
            workload=PanelWorkloadConfig(
                batch_size=config.workload.task_count,
                request_size_bytes=config.workload.request_size_bytes,
                request_merge=False,
            ),
        )
    )


class StaticOwnershipMotivationTests(unittest.TestCase):
    def test_owner_vectors_have_exact_counts_and_no_overlap(self) -> None:
        config = _config(seeds=(31,))
        for counts in OWNER_DISTRIBUTIONS.values():
            tasks = build_paired_unique_tasks(
                _simulator(config),
                counts,
                task_count=640,
                request_size_bytes=64 * 1024**2,
                seed=31,
            )

            self.assertEqual(
                tuple(Counter(task.zone_id for task in tasks)[zone] for zone in range(8)),
                counts,
            )
            self.assertEqual(len(tasks), 640)
            self.assertEqual(len({task.platter_id for task in tasks}), 640)

    def test_reader_relative_coordinates_are_paired_and_right_is_mirrored(self) -> None:
        config = _config(seeds=(31,))
        all_tasks = [
            build_paired_unique_tasks(
                _simulator(config),
                counts,
                640,
                64 * 1024**2,
                31,
            )
            for counts in OWNER_DISTRIBUTIONS.values()
        ]
        signatures = [
            [
                reader_relative_signature(task, 400, 2)
                for task in tasks
            ]
            for tasks in all_tasks
        ]

        self.assertEqual(signatures[0], signatures[1])
        self.assertEqual(signatures[0], signatures[2])
        for task, (_, distance) in zip(all_tasks[1], signatures[1]):
            if task.side == "right":
                self.assertEqual(task.slot_in_half, 399 - distance)

    def test_logical_requests_merge_to_exactly_640_targets(self) -> None:
        config = _config(seeds=(31,))
        targets = build_paired_unique_tasks(
            _simulator(config),
            OWNER_DISTRIBUTIONS["moderate"],
            640,
            64 * 1024**2,
            31,
        )
        logical = expand_logical_requests(
            targets,
            logical_request_count=10_000,
            request_size_bytes=64 * 1024**2,
            seed=31,
        )
        merged = merge_panel_requests(logical)

        self.assertEqual(len(logical), 10_000)
        self.assertEqual(len(merged), 640)
        self.assertEqual(
            Counter(task.merged_request_count for task in merged),
            {15: 240, 16: 400},
        )
        self.assertEqual(
            sum(task.size_bytes for task in logical),
            sum(task.size_bytes for task in merged),
        )
        observed = Counter(task.zone_id for task in merged)
        self.assertEqual(
            tuple(observed[zone] for zone in range(8)),
            OWNER_DISTRIBUTIONS["moderate"],
        )

    def test_study_is_reproducible_and_metrics_are_monotonic(self) -> None:
        config = _config()
        first = run_static_ownership_motivation(config)
        second = run_static_ownership_motivation(config)

        self.assertEqual(first.run_rows, second.run_rows)
        self.assertTrue(first.validation["passed"])
        self.assertEqual(first.validation["checked_runs"], 12)
        targets = {
            row["scenario"]: row["target_busiest_owner_amplification_mean"]
            for row in first.aggregate_rows
            if row["mode"] == MERGED_MODE
        }
        self.assertEqual(targets, {"balanced": 1.0, "moderate": 2.0, "strong": 4.0})
        for mode in ("unique_tasks", MERGED_MODE):
            rows = {
                row["scenario"]: row
                for row in first.aggregate_rows
                if row["mode"] == mode
            }
            drains = [
                rows[name]["system_drain_over_balanced_mean"]
                for name in OWNER_DISTRIBUTIONS
            ]
            stranded = [
                rows[name]["stranded_capacity_share_mean"]
                for name in OWNER_DISTRIBUTIONS
            ]
            self.assertEqual(drains, sorted(drains))
            self.assertEqual(stranded, sorted(stranded))
            for row in rows.values():
                self.assertEqual(row["physical_task_count_mean"], 640)
                self.assertEqual(row["shuttle_count_mean"], 8)
                self.assertEqual(row["reader_count_mean"], 8)


if __name__ == "__main__":
    unittest.main()
