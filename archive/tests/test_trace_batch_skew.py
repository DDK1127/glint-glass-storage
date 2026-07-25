from __future__ import annotations

from collections import Counter
from pathlib import Path
import unittest

from glass_v2.panel_static_zone import (
    PanelGeometryConfig,
    PanelMovementConfig,
    PanelStaticZoneConfig,
    PanelStaticZoneSimulator,
    PanelTimingConfig,
    PanelWorkloadConfig,
    merge_panel_requests,
)
from glass_v2.trace_batch_skew import (
    BatchWorkloadConfig,
    MappedTraceRequest,
    logical_request_signature,
    reorder_logical_requests,
)


def _simulator() -> PanelStaticZoneSimulator:
    return PanelStaticZoneSimulator(
        PanelStaticZoneConfig(
            output_dir=Path("outputs/test-trace-batch-skew"),
            seed=1,
            geometry=PanelGeometryConfig(8, 2, 16.0, 400, 8 * 1024**3),
            movement=PanelMovementConfig(2.0, 2.0, 1.0, 3.0),
            timing=PanelTimingConfig(3.0, 3.0, 3.0, 3.0, 1.0, 0.00035, 60.0),
            workload=PanelWorkloadConfig(100, 4096, request_merge=True),
        )
    )


def _mapped_requests(count: int = 800) -> list[MappedTraceRequest]:
    return [
        MappedTraceRequest(
            source_index=index,
            size_bytes=4096,
            platter_id=index % 80,
            zone_id=index % 8,
            local_level=0,
            slot_in_half=index % 400,
        )
        for index in range(count)
    ]


class TraceBatchSkewTests(unittest.TestCase):
    def test_batch_wide_merge_combines_all_same_glass_requests(self) -> None:
        simulator = _simulator()
        requests = [simulator.make_request(index, 0, 0, 10, 4096) for index in range(5)]

        merged = merge_panel_requests(requests)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].merged_request_count, 5)
        self.assertEqual(merged[0].size_bytes, 5 * 4096)
        self.assertEqual(merged[0].request_index, 0)

    def test_merge_does_not_cross_batch_boundary(self) -> None:
        simulator = _simulator()
        first = merge_panel_requests([simulator.make_request(0, 0, 0, 10, 4096)])
        second = merge_panel_requests([simulator.make_request(1, 0, 0, 10, 4096)])

        self.assertEqual(len(first) + len(second), 2)

    def test_order_only_generator_preserves_requests_and_zone_internal_order(self) -> None:
        requests = _mapped_requests()
        workload = BatchWorkloadConfig("severe", "Severe", 0.8)

        ordered = reorder_logical_requests(requests, workload, 8, 100, 3)

        self.assertEqual(logical_request_signature(requests), logical_request_signature(ordered))
        for zone in range(8):
            original = [request.source_index for request in requests if request.zone_id == zone]
            changed = [request.source_index for request in ordered if request.zone_id == zone]
            self.assertEqual(original, changed)

    def test_severe_batch_targets_eighty_percent_from_one_zone(self) -> None:
        requests = _mapped_requests()
        workload = BatchWorkloadConfig("severe", "Severe", 0.8)

        ordered = reorder_logical_requests(requests, workload, 8, 100, 3)
        counts = Counter(request.zone_id for request in ordered[:100])

        self.assertGreaterEqual(max(counts.values()), 80)


if __name__ == "__main__":
    unittest.main()
