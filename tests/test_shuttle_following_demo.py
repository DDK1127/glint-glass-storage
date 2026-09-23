from dataclasses import replace
import unittest

from glass_sim.shuttle_following_demo import FollowingConfig, run_following


class FollowingTests(unittest.TestCase):
    def test_braking_and_delay(self):
        result = run_following(FollowingConfig())
        s = result["summary"]
        self.assertEqual((s["brake_start_s"], s["brake_end_s"]), (1.5, 2.5))
        self.assertEqual(s["braking_trigger_gap_m"], 2.5)
        self.assertEqual(s["minimum_center_gap_m"], 2)
        self.assertEqual((s["follower_checkpoint_s"], s["added_checkpoint_time_s"]), (8, 3))
        self.assertEqual(sum(p["duration_s"] for p in result["phases"]), 8)
        self.assertTrue(all(r["center_gap_m"] >= 2-1e-9 for r in result["samples"]))

    def test_unsafe_initial_state_rejected(self):
        with self.assertRaisesRegex(ValueError, "Insufficient gap"):
            run_following(FollowingConfig(initial_center_gap_m=2.1))

    def test_sampling_does_not_determine_safety_or_finish(self):
        config = FollowingConfig()
        self.assertEqual(run_following(config)["summary"], run_following(replace(config, sample_interval_s=3))["summary"])

    def test_checkpoints_during_cruise_and_braking(self):
        for target in (1, 4, 10):
            result = run_following(FollowingConfig(checkpoint_m=target))
            finish = result["summary"]["follower_checkpoint_s"]
            point = next(r for r in result["samples"] if r["time_s"] == finish)
            self.assertAlmostEqual(point["follower_x_m"], target)

    def test_zero_delay_before_catchup(self):
        self.assertEqual(run_following(FollowingConfig(checkpoint_m=1))["summary"]["added_checkpoint_time_s"], 0)
