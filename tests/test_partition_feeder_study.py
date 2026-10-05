from dataclasses import replace
import unittest

from glass_sim.partition_feeder_study import Config, PartitionSimulation, Rail, Request, make_requests


class PartitionFeederTests(unittest.TestCase):
    def test_single_request_matches_hand_calculation(self):
        c = Config(shuttles=1, buffer_slots=0)
        request = Request(0, 5.0, 3*c.slots_per_row)
        rail = Rail(c)
        travel = sum(t for _, t in rail.path(Rail.READER, c.home(request.platter)))
        result, jobs, _ = PartitionSimulation(c, [request]).run()
        expected = 2*travel+c.pick_s+c.handoff_s+c.load_mount_s+c.read_s
        self.assertAlmostEqual(result['mean_s'], expected)
        self.assertAlmostEqual(jobs[0]['returned_s'], 5+expected+c.unload_s+c.pick_s+travel+c.place_s)

    def test_segment_reservations_allow_disjoint_connector_motion(self):
        rail = Rail(Config())
        first = rail.reserve((0, 0), (1, 0), 0, 0, 0, 'move')
        second = rail.reserve((5, 0), (6, 0), 0, 1, 1, 'move')
        reverse = rail.reserve((1, 0), (0, 0), 0, 2, 2, 'move')
        self.assertEqual(first[0], second[0])
        self.assertGreaterEqual(reverse[0], first[1])
        rail.validate()

    def test_calendar_reuses_gaps(self):
        rail = Rail(Config())
        rail.reserve((0, 0), (1, 0), 20, 0, 0, 'late')
        start, end = rail.reserve((0, 0), (1, 0), 0, 1, 1, 'early')
        self.assertEqual(start, 0)
        self.assertEqual(end, 3)
        rail.validate()

    def test_yield_penalty_applies_only_after_resource_contention(self):
        rail = Rail(replace(Config(), yield_penalty_s=2.0))
        first = rail.reserve((0, 0), (1, 0), 0, 0, 0, 'move')
        second = rail.reserve((0, 0), (1, 0), 0, 1, 1, 'move')
        independent = rail.reserve((5, 0), (6, 0), 0, 2, 2, 'move')
        self.assertAlmostEqual(second[0], first[1] + 2.0)
        self.assertEqual(independent[0], 0)
        rail.validate()

    def test_yield_penalty_rechecks_future_reservation(self):
        rail = Rail(replace(Config(), yield_penalty_s=2.0))
        rail.reserve((0, 0), (1, 0), 0, 0, 0, 'first')
        rail.reserve((0, 0), (1, 0), 5, 1, 1, 'future')
        start, _, _, _ = rail.estimate((0, 0), (1, 0), 0)
        self.assertAlmostEqual(start, 10.0, places=6)

    def test_all_policies_preserve_same_work_with_one_reader(self):
        c = Config()
        requests = make_requests(c, 48, 101, 'hotspot')
        hashes = set()
        for n in [1, 2, 4, 8]:
            for policy in ['zone', 'nonzone_fifo', 'nonzone_local']:
                for b in [0, 1, 4]:
                    cfg = replace(c, shuttles=n, policy=policy, buffer_slots=b)
                    sim = PartitionSimulation(cfg, requests)
                    s, jobs, _ = sim.run()
                    hashes.add(s['workload_sha256'])
                    self.assertEqual(s['returned'], len(requests))
                    self.assertLessEqual(s['max_input'], b)
                    self.assertLessEqual(s['max_dock'], 8)
                    self.assertLessEqual(s['max_output'], 8)
                    self.assertLessEqual(s['reader_busy_fraction'], 1)
                    if policy == 'zone':
                        self.assertTrue(all(j['shuttle']==cfg.owner(j['platter']) for j in jobs))
        self.assertEqual(len(hashes), 1)

    def test_single_shuttle_zone_and_fifo_equivalent(self):
        c = Config(shuttles=1)
        r = make_requests(c, 40, 22)
        zone = PartitionSimulation(replace(c, policy='zone'), r).run()
        fifo = PartitionSimulation(replace(c, policy='nonzone_fifo'), r).run()
        self.assertEqual(zone, fifo)

    def test_finite_buffer_frees_shuttle_before_read_finishes(self):
        c = Config(shuttles=1, read_s=200, buffer_slots=1)
        requests = [Request(i, 0, 240+i) for i in range(4)]
        _, jobs, _ = PartitionSimulation(c, requests).run()
        self.assertLess(jobs[1]['handoff_done_s'], jobs[0]['read_done_s'])
        _, direct, _ = PartitionSimulation(replace(c, buffer_slots=0), requests).run()
        self.assertGreater(direct[1]['delivery_wait_s'], 0)

    def test_prefetch_metrics_distinguish_handoff_overlap_from_motion(self):
        c = Config(shuttles=4, buffer_slots=4, read_s=24)
        requests = make_requests(c, 32, 7, 'uniform')
        summary, _, _ = PartitionSimulation(c, requests).run()
        self.assertGreater(summary['prefetch_hit_fraction'], 0.0)
        self.assertGreater(summary['prefetch_lead_mean_s'], 0.0)
        self.assertGreater(summary['route_motion_s'], 0.0)

    def test_repeat_platter_and_late_arrival_are_causal(self):
        c = Config()
        _, jobs, _ = PartitionSimulation(c, [Request(0,0,0), Request(1,0,0), Request(2,1000,1)]).run()
        self.assertGreaterEqual(jobs[1]['dispatch_s'], jobs[0]['returned_s'])
        self.assertGreaterEqual(jobs[2]['dispatch_s'], 1000)

    def test_reproducible_and_online_timestamps_paired(self):
        c = Config()
        a = make_requests(c, 30, 2, 'uniform', .1)
        b = make_requests(c, 30, 2, 'hotspot', .1)
        self.assertEqual([r.arrival_s for r in a], [r.arrival_s for r in b])
        self.assertEqual(PartitionSimulation(c,a).run(), PartitionSimulation(c,a).run())

    def test_invalid_parameters(self):
        with self.assertRaises(ValueError):
            replace(Config(), shuttles=3, policy='zone').validate()
        with self.assertRaises(ValueError):
            replace(Config(), shuttles=0).validate()
        with self.assertRaises(ValueError):
            replace(Config(), shuttles=33, docking_bays=33).validate()
        with self.assertRaises(ValueError):
            replace(Config(), shuttles=16, policy='zone', docking_bays=32).validate()
        with self.assertRaises(ValueError):
            replace(Config(), read_s=float('nan')).validate()
        with self.assertRaises(ValueError):
            PartitionSimulation(Config(), [Request(0,0,10000)])

    def test_nonzone_supports_more_than_one_shuttle_per_row(self):
        config = Config(shuttles=16, policy='nonzone_fifo', buffer_slots=8, docking_bays=32)
        summary, jobs, _ = PartitionSimulation(config, make_requests(config, 48, 88)).run()
        self.assertEqual(summary['returned'], 48)
        self.assertEqual(len(jobs), 48)

    def test_nonzone_accepts_non_power_of_two_fleet(self):
        config = Config(shuttles=5, policy='nonzone_fifo', buffer_slots=4, docking_bays=32)
        summary, _, _ = PartitionSimulation(config, make_requests(config, 40, 7)).run()
        self.assertEqual(summary['returned'], 40)


    def test_contention_hold_occupies_block_and_lowers_dense_throughput(self):
        free = Config(shuttles=16, policy='nonzone_fifo', buffer_slots=4, docking_bays=32)
        congested = replace(free, contention_hold_s=1.0)
        requests = make_requests(free, 96, 5)
        base, _, _ = PartitionSimulation(free, requests).run()
        slow, _, _ = PartitionSimulation(congested, requests).run()  # run() rejects overlapping reservations
        self.assertEqual(base['contended_steps'], 0)
        self.assertGreater(slow['contended_steps'], 0)
        self.assertLess(slow['throughput_req_s'], base['throughput_req_s'])
        with self.assertRaises(ValueError):
            replace(free, contention_hold_s=-1.0).validate()

if __name__ == '__main__':
    unittest.main()
