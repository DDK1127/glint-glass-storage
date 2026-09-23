from pathlib import Path
import tempfile
import unittest

from glass_sim.azure_capacity_scalability import VirtualPlatterWork
from glass_sim.no_zone_conflict import exposure
from glass_sim.zone_nozone_comparison import (
    NO_ZONE,
    NO_ZONE_VIRTUAL,
    STATIC_ZONE,
    ComparisonConfig,
    physical_positions,
    simulate_policy,
)


def config(root: Path) -> ComparisonConfig:
    batch = root / "batch.csv.gz"
    batch.write_bytes(b"placeholder")
    return ComparisonConfig(
        output_dir=root / "results",
        batch_path=batch,
        batch_sha256="0" * 64,
        seeds=(1,),
        lengths_m=(8,),
        platter_count=32,
        levels=8,
        mapping_slots_per_level=10,
        level_spacing_m=0.5,
        speed_m_s=2,
        acceleration_m_s2=2,
        crab_s_per_level=3,
        clearance_x_m=0.25,
        clearance_y_m=0.25,
        pick_s=1,
        place_s=1,
        reader_load_s=1,
        reader_unload_s=1,
        reader_mount_s=1,
        reader_mib_s=60,
    )


class PolicyComparisonTests(unittest.TestCase):
    def test_policies_preserve_work_and_are_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cfg = config(Path(directory))
            work = [
                VirtualPlatterWork(i, i, (i + 1) * 1024, 2, 1)
                for i in range(32)
            ]
            positions = physical_positions(work, cfg, 9, 8)
            static = simulate_policy(work, positions, cfg, STATIC_ZONE)
            no_zone = simulate_policy(work, positions, cfg, NO_ZONE)
            repeated = simulate_policy(work, positions, cfg, NO_ZONE)

        self.assertEqual(no_zone, repeated)
        for summary, jobs, _ in (static, no_zone):
            self.assertEqual(summary["physical_tasks"], 32)
            self.assertEqual(summary["logical_requests"], 64)
            self.assertEqual(len({job.task_id for job in jobs}), 32)
        self.assertEqual(static[0]["unique_bytes"], no_zone[0]["unique_bytes"])

    def test_static_uses_owner_and_no_zone_can_cross_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cfg = config(Path(directory))
            work = [
                VirtualPlatterWork(i, i, 1024, 1, 1)
                for i in range(32)
            ]
            positions = physical_positions(work, cfg, 3, 8)
            _, static_jobs, _ = simulate_policy(work, positions, cfg, STATIC_ZONE)
            _, no_zone_jobs, _ = simulate_policy(work, positions, cfg, NO_ZONE)

        self.assertTrue(
            all(job.shuttle_id == job.zone_id for job in static_jobs)
        )
        self.assertTrue(
            any(job.shuttle_id != job.zone_id for job in no_zone_jobs)
        )

    def test_no_zone_schedule_is_conflict_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cfg = config(Path(directory))
            work = [
                VirtualPlatterWork(i, i, 2048, 1, 1)
                for i in range(24)
            ]
            positions = physical_positions(work, cfg, 4, 8)
            summary, jobs, segments = simulate_policy(
                work, positions, cfg, NO_ZONE
            )

        self.assertGreaterEqual(summary["conflict_wait_s"], 0)
        self.assertGreaterEqual(summary["detour_s"], 0)
        self.assertLessEqual(summary["reader_utilization"], 1)
        self.assertFalse(exposure(segments, cfg.motion_dict()))
        for job in jobs:
            self.assertAlmostEqual(
                job.actual_cycle_s - job.base_cycle_s,
                job.conflict_wait_s + job.detour_s + job.reader_queue_s,
                places=6,
            )
            self.assertAlmostEqual(
                job.conflict_wait_s + job.detour_s,
                job.fetch_coordination_s
                + job.pick_coordination_s
                + job.delivery_coordination_s
                + job.reader_coordination_s
                + job.return_coordination_s
                + job.place_coordination_s,
                places=6,
            )

    def test_virtual_no_zone_removes_collision_costs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cfg = config(Path(directory))
            work = [VirtualPlatterWork(i, i, 2048, 1, 1) for i in range(32)]
            positions = physical_positions(work, cfg, 7, 8)
            summary, jobs, _ = simulate_policy(
                work, positions, cfg, NO_ZONE_VIRTUAL
            )

        self.assertEqual(summary["physical_tasks"], 32)
        self.assertEqual(summary["conflict_wait_s"], 0)
        self.assertEqual(summary["detour_s"], 0)
        self.assertTrue(all(job.conflict_count == 0 for job in jobs))
