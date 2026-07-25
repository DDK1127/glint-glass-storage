from __future__ import annotations

from pathlib import Path
import unittest

from glass_v2.panel_static_zone import (
    PanelGeometryConfig,
    PanelMovementConfig,
    PanelStaticZoneConfig,
    PanelStaticZoneSimulator,
    PanelTimingConfig,
    PanelWorkloadConfig,
)
from glass_v2.trace_temporal_skew import (
    TemporalWorkloadConfig,
    reorder_tasks_for_workload,
    task_multiset_signature,
)


def _simulator() -> PanelStaticZoneSimulator:
    config = PanelStaticZoneConfig(
        output_dir=Path("outputs/test-temporal-skew"),
        seed=1,
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
            batch_size=80,
            request_size_bytes=4096,
            request_merge=True,
        ),
    )
    return PanelStaticZoneSimulator(config)


def _tasks(simulator: PanelStaticZoneSimulator):
    tasks = []
    for index in range(80):
        zone = index % 8
        tasks.append(simulator.make_request(index, zone, 0, index, 4096))
    return tasks


class TraceTemporalSkewTests(unittest.TestCase):
    def test_reordering_preserves_task_multiset_and_zone_internal_order(self) -> None:
        simulator = _simulator()
        tasks = _tasks(simulator)
        workload = TemporalWorkloadConfig("severe", "Severe", 0.8)

        ordered = reorder_tasks_for_workload(tasks, workload, 8, 10, 3)

        self.assertEqual(task_multiset_signature(tasks), task_multiset_signature(ordered))
        for zone in range(8):
            original = [task.request_index for task in tasks if task.zone_id == zone]
            reordered = [task.request_index for task in ordered if task.zone_id == zone]
            self.assertEqual(original, reordered)

    def test_severe_order_creates_hot_epochs(self) -> None:
        simulator = _simulator()
        tasks = _tasks(simulator)
        workload = TemporalWorkloadConfig("severe", "Severe", 0.8)

        ordered = reorder_tasks_for_workload(tasks, workload, 8, 10, 3)
        first_epoch = ordered[:10]
        zone_counts = [sum(task.zone_id == zone for task in first_epoch) for zone in range(8)]

        self.assertGreaterEqual(max(zone_counts), 8)

    def test_barrier_epoch_waits_for_previous_epoch_drain(self) -> None:
        simulator = _simulator()
        tasks = _tasks(simulator)

        result, epochs = simulator.run_barrier_epochs([tasks[:8], tasks[8:16]])

        first_drain = max(detail.return_done_s for detail in epochs[0])
        self.assertTrue(all(detail.arrival_s == first_drain for detail in epochs[1]))
        self.assertEqual(len(result.details), 16)


if __name__ == "__main__":
    unittest.main()
