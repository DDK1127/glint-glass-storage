from dataclasses import replace
import random
import unittest

from glass_sim.io_scheduler import (FIFO, GiB, IOConfig, IOSimulation, MiB, Request, SilicaFIFO,
                                    draw_size, lower_bound, make_burst)
from glass_sim.partition_feeder_study import Rail


class IOSchedulerTests(unittest.TestCase):
    def test_single_request_matches_hand_calculation(self):
        c = IOConfig()
        r = Request(0, 0.0, 3 * c.slots_per_row + 40, 30 * 10**6)
        one_way = sum(d for _, d in Rail(c).path(Rail.READER, c.home(r.platter)))
        sim = IOSimulation(c, [r], SilicaFIFO())
        s = sim.run()
        expected = 2 * one_way + c.pick_s + c.handoff_s + c.load_mount_s + c.request_overhead_s + 1.0
        self.assertAlmostEqual(s["makespan_s"], expected)
        self.assertLessEqual(s["lower_bound_s"], s["makespan_s"] + 1e-9)

    def test_merge_serves_same_platter_in_one_trip(self):
        c = IOConfig()
        reqs = [Request(i, 0.0, 5, MiB) for i in range(3)]
        self.assertEqual(IOSimulation(c, reqs, SilicaFIFO()).run()["trips"], 1)
        self.assertEqual(IOSimulation(c, reqs, FIFO()).run()["trips"], 3)

    def test_late_request_joins_trip_in_flight(self):
        c = IOConfig()
        reqs = [Request(0, 0.0, 5, MiB), Request(1, 3.0, 5, MiB)]
        sim = IOSimulation(c, reqs, SilicaFIFO())
        s = sim.run()
        self.assertEqual(s["trips"], 1)
        self.assertEqual(sim.trips[0]["requests"], [0, 1])

    def test_lower_bound_holds_and_zone_ownership(self):
        c = IOConfig()
        for seed in range(4):
            for platters in (None, 12):
                reqs = make_burst(c, 120, seed, platters=platters, window_s=30.0)
                for sched in (FIFO(), SilicaFIFO()):
                    sim = IOSimulation(c, reqs, sched)
                    s = sim.run()
                    self.assertLessEqual(s["lower_bound_s"], s["makespan_s"] + 1e-6)
                    self.assertTrue(all(t["shuttle"] == c.owner(t["platter"]) for t in sim.trips))
                    self.assertEqual(sum(len(t["requests"]) for t in sim.trips), len(reqs))
                    self.assertLessEqual(s["reader_busy_fraction"], 1 + 1e-9)

    def test_reproducible(self):
        c = IOConfig()
        reqs = make_burst(c, 60, 7)
        self.assertEqual(reqs, make_burst(c, 60, 7))
        self.assertEqual(IOSimulation(c, reqs, SilicaFIFO()).run()["makespan_s"],
                         IOSimulation(c, reqs, SilicaFIFO()).run()["makespan_s"])

    def test_size_mix_matches_silica_shares(self):
        rng = random.Random(3)
        sizes = [draw_size(rng) for _ in range(200000)]
        small = sum(s <= 4 * MiB for s in sizes) / len(sizes)
        large_bytes = sum(s for s in sizes if s > 256 * MiB) / sum(sizes)
        self.assertAlmostEqual(small, 0.587, delta=0.01)
        self.assertAlmostEqual(large_bytes, 0.85, delta=0.05)
        self.assertLessEqual(max(sizes), 32 * GiB)

    def test_cache_serves_repeat_without_second_fetch(self):
        c = IOConfig(cache_slots=2)
        reqs = [Request(0, 0.0, 5, MiB), Request(1, 500.0, 5, MiB)]
        sim = IOSimulation(c, reqs, SilicaFIFO())
        s = sim.run()
        self.assertEqual((s["trips"], s["cache_hits"], s["fetch_trips"]), (2, 1, 1))
        self.assertTrue(sim.trips[1]["from_cache"])
        no_cache = IOSimulation(replace(c, cache_slots=0), reqs, SilicaFIFO()).run()
        self.assertEqual(no_cache["fetch_trips"], 2)
        self.assertLess(s["makespan_s"], no_cache["makespan_s"])

    def test_cache_evicts_least_recently_used(self):
        c = IOConfig(cache_slots=1)
        reqs = [Request(0, 0.0, 5, MiB), Request(1, 300.0, 6, MiB), Request(2, 600.0, 5, MiB)]
        sim = IOSimulation(c, reqs, SilicaFIFO())
        s = sim.run()
        self.assertEqual((s["fetch_trips"], s["cache_hits"]), (3, 0))   # 5 was evicted by 6
        self.assertEqual(s["evictions"], 2)
        self.assertEqual(list(sim.cache), [5])

    def test_cache_conserves_requests_and_capacity(self):
        c = IOConfig(cache_slots=4)
        for seed in range(3):
            reqs = make_burst(c, 150, seed, platters=20, window_s=600.0)
            sim = IOSimulation(c, reqs, SilicaFIFO())
            s = sim.run()
            self.assertEqual(sum(len(t["requests"]) for t in sim.trips), len(reqs))
            self.assertLessEqual(len(sim.cache), 4)
            self.assertGreater(s["cache_hits"], 0)

    def test_invalid_parameters(self):
        with self.assertRaises(ValueError):
            replace(IOConfig(), cache_slots=2, buffer_slots=0).validate()
        with self.assertRaises(ValueError):
            replace(IOConfig(), shuttles=3).validate()
        with self.assertRaises(ValueError):
            replace(IOConfig(), read_mb_s=0.0).validate()
        with self.assertRaises(ValueError):
            make_burst(IOConfig(), 10, 1, platters=0)


if __name__ == "__main__":
    unittest.main()
