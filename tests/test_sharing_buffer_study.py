from dataclasses import replace
import unittest

from glass_sim.sharing_buffer_study import Model, Request, Simulator, Transport, horizontal_time, workload


class SharingBufferTests(unittest.TestCase):
    def test_single_request_hand_calculation(self):
        model = Model()
        request = Request(0, 7.0, 0)
        summary, jobs, _ = Simulator(model, [request], "fixed", 1, 0).run()
        trip = horizontal_time(model.position(0)[1], model) + model.alignment_s
        expected = 2 * trip + model.pick_s + model.handoff_s + model.read_service_s
        self.assertAlmostEqual(summary["latency_mean_s"], expected)
        self.assertAlmostEqual(jobs[0]["returned_s"], 7 + expected + model.unload_s + model.pick_s + trip + model.place_s)
        self.assertEqual(summary["idle_reader_with_demand_s"], expected - model.read_service_s - model.handoff_s)

    def test_transport_exclusion_and_parallel_local_lanes(self):
        transport = Transport(Model())
        first = transport.reserve((0, 0), (0, 8), 0, 0, 0, "fetch")
        second = transport.reserve((0, 0), (0, 4), 0, 1, 1, "fetch")
        third = transport.reserve((1, 0), (1, 4), 0, 2, 2, "fetch")
        self.assertEqual(second[0], first[1])
        self.assertEqual(third[0], 0)
        a = transport.reserve((0, 0), (4, 0), 10, 0, 0, "cross")
        b = transport.reserve((6, 0), (2, 0), 10, 1, 1, "cross")
        self.assertEqual(b[0], a[1])
        transport.validate()

    def test_all_modes_conserve_requests_and_finite_resources(self):
        model = Model()
        trace = workload(model, 40, 5, .8, "hotspot")
        for mode, group in [("fixed", 1), ("transport", 2), ("joint", 2), ("transport", 8), ("joint", 8)]:
            for capacity in [0, 1, 4]:
                with self.subTest(mode=mode, group=group, capacity=capacity):
                    sim = Simulator(model, trace, mode, group, capacity)
                    result, jobs, _ = sim.run()
                    self.assertEqual(result["returned"], len(trace))
                    self.assertLessEqual(result["max_input_depth"], capacity)
                    for job in jobs:
                        self.assertEqual(job["shuttle"] // group, job["home"] // group)
                        self.assertEqual(job["reader"] // group, job["home"] // group)
                        if mode != "joint":
                            self.assertEqual(job["reader"], job["home"])
                        self.assertGreaterEqual(job["read_done_s"], job["arrival_s"])

    def test_group_one_emulates_fixed_and_reproduces(self):
        model = Model()
        trace = workload(model, 24, 8, .4, "uniform")
        fixed = Simulator(model, trace, "fixed", 1, 1).run()
        self.assertEqual(fixed, Simulator(model, trace, "fixed", 1, 1).run())
        for mode in ["joint", "transport"]:
            other = Simulator(model, trace, mode, 1, 1).run()
            self.assertEqual(fixed[1:], other[1:])
            self.assertEqual(fixed[0]["latency_p99_s"], other[0]["latency_p99_s"])

    def test_platter_must_return_before_reuse(self):
        trace = [Request(i, 0.0, 0) for i in range(3)]
        _, jobs, _ = Simulator(Model(), trace, "joint", 8, 4).run()
        for a, b in zip(jobs, jobs[1:]):
            self.assertGreaterEqual(b["dispatch_s"], a["returned_s"])

    def test_no_service_before_late_arrival(self):
        trace = [Request(0, 0, 0), Request(1, 1000, 81)]
        _, jobs, _ = Simulator(Model(), trace, "joint", 8, 1).run()
        self.assertGreaterEqual(jobs[1]["dispatch_s"], 1000)

    def test_input_can_overlap_reader_without_holding_shuttle(self):
        model = replace(Model(), read_mib=6000)
        trace = [Request(i, 0.0, i) for i in range(5)]
        _, jobs, _ = Simulator(model, trace, "fixed", 1, 1).run()
        self.assertLess(jobs[1]["handoff_done_s"], jobs[0]["read_done_s"])
        self.assertGreater(jobs[1]["read_start_s"], jobs[1]["handoff_done_s"])
        _, direct, _ = Simulator(model, trace, "fixed", 1, 0).run()
        self.assertGreater(direct[1]["delivery_wait_s"], 0)

    def test_finite_output_blocks_unloading_when_returns_are_late(self):
        model = replace(Model(), read_mib=6)
        trace = [Request(i, 0.0, i * 13 % 80) for i in range(16)]
        sim = Simulator(model, trace, "joint", 8, 4)
        result, jobs, _ = sim.run()
        self.assertGreater(result["output_block_s"], 0)
        self.assertEqual(len(jobs), result["returned"])

    def test_workloads_pair_timestamps_and_sizes_without_future_knowledge(self):
        model = Model()
        uniform = workload(model, 96, 4, .3, "uniform")
        hotspot = workload(model, 96, 4, .3, "hotspot")
        self.assertEqual([r.arrival_s for r in uniform], [r.arrival_s for r in hotspot])
        self.assertEqual([r.platter % 80 for r in uniform], [r.platter % 80 for r in hotspot])
        self.assertEqual(uniform[:32], hotspot[:32])
        self.assertEqual(uniform[64:], hotspot[64:])
        self.assertNotEqual(uniform[32:64], hotspot[32:64])

    def test_invalid_configuration_rejected(self):
        with self.assertRaises(ValueError):
            replace(Model(), read_mib=float("nan")).validate()
        with self.assertRaises(ValueError):
            Simulator(Model(), [Request(0, 0, 0)], "joint", 3, 1)
        with self.assertRaises(ValueError):
            Simulator(Model(), [Request(0, 0, 0)], "fixed", 1, -1)


if __name__ == "__main__":
    unittest.main()
