from pathlib import Path
import tempfile
import unittest

from glass_sim.azure_capacity_scalability import VirtualPlatterWork
from glass_sim.no_zone_conflict import exposure
from glass_sim.windowed_cbs_study import simulate_windowed_cbs
from tests.test_zone_nozone_comparison import config


class WindowedCBSStudyTests(unittest.TestCase):
    def test_services_all_tasks_and_returns_conflict_free_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = config(Path(directory))
            work = [VirtualPlatterWork(i, i, 1024, 1, 1) for i in range(8)]
            positions = {
                zone: (
                    zone // 4,
                    2.0 + (zone % 2),
                    ((zone % 4) * 2) * cfg.level_spacing_m,
                )
                for zone in range(8)
            }
            summary, jobs, segments = simulate_windowed_cbs(
                work,
                positions,
                cfg,
                tasks_per_side_window=2,
                max_cbs_nodes=64,
            )
            repeated = simulate_windowed_cbs(
                work,
                positions,
                cfg,
                tasks_per_side_window=2,
                max_cbs_nodes=64,
            )

        self.assertEqual(summary["physical_tasks"], 8)
        self.assertEqual(summary["logical_requests"], 8)
        self.assertEqual(len({job.task_id for job in jobs}), 8)
        self.assertGreater(summary["cbs_windows"], 0)
        self.assertFalse(exposure(segments, cfg.motion_dict()))
        self.assertEqual((summary, jobs, segments), repeated)


if __name__ == "__main__":
    unittest.main()
