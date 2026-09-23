from pathlib import Path
import tempfile
import unittest

from glass_sim.buffered_32rack_study import (
    BufferedRackConfig,
    NO_ZONE,
    STATIC_ZONE,
    ZONE,
    simulate,
)
from glass_sim.zone_nozone_trace import Read
from tests.test_zone_nozone_comparison import config as base_config


class Buffered32RackStudyTests(unittest.TestCase):
    def test_policies_conserve_requests_and_return_every_platter(self):
        with tempfile.TemporaryDirectory() as directory:
            base = base_config(Path(directory))
            cfg = BufferedRackConfig(
                output_dir=Path(directory) / "results",
                base=base,
                seeds=(1,),
                rack_count=32,
                rack_length_m=16,
                rack_spacing_m=1,
                slots_per_rack=10,
                reader_count=8,
                buffer_slots_per_reader=4,
                output_return_threshold=8,
                buffer_drop_s=1,
            )
            reads = [Read(index, 0, (str(index), "v"), 1024) for index in range(32)]
            mapped = {request.key: request.index for request in reads}
            positions = {
                index: (2 + index % 4, index * cfg.rack_spacing_m)
                for index in range(32)
            }
            results = {
                policy: simulate(reads, mapped, positions, cfg, policy)[0]
                for policy in (STATIC_ZONE, ZONE, NO_ZONE)
            }

        for result in results.values():
            self.assertEqual(result["logical_requests"], 32)
            self.assertEqual(result["physical_services"], result["return_services"])
            self.assertLessEqual(result["reader_utilization"], 1)
            self.assertLessEqual(result["max_input_buffer_depth"], 4)
        self.assertEqual(results[ZONE]["conflict_wait_s"], 0)
        self.assertEqual(results[STATIC_ZONE]["conflict_wait_s"], 0)
        self.assertEqual(results[STATIC_ZONE]["rack_shuttle_count"], 8)
        self.assertEqual(results[ZONE]["rack_shuttle_count"], 32)


if __name__ == "__main__":
    unittest.main()
