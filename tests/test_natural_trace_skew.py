from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from glass_sim.natural_trace_skew import (
    MappedNaturalRequest,
    NaturalPlacementConfig,
    NaturalTraceSkewConfig,
    count_windows,
    load_sorted_read_requests,
    map_trace_requests,
    summarize_window,
    time_windows,
)
from glass_sim.panel_static_zone import (
    PanelGeometryConfig,
    PanelMovementConfig,
    PanelTimingConfig,
)
from glass_sim.trace import TraceRequest


def _config() -> NaturalTraceSkewConfig:
    return NaturalTraceSkewConfig(
        output_dir=Path("results/test-natural-trace-skew"),
        trace_path=Path("unused.csv"),
        max_read_requests=None,
        request_count_windows=(4,),
        time_windows_s=(1.0,),
        hotspot_work_share_threshold=0.25,
        primary_count_window=4,
        primary_time_window_s=1.0,
        heatmap_placement="hash",
        validation_sample_windows=1,
        stripe_bytes=100,
        platter_count=6400,
        placements=(
            NaturalPlacementConfig("hash", "Hash", "randomized_hash", "hash", 7),
        ),
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
    )


def _mapped(index: int, arrival_s: float, platter_id: int, size_bytes: int = 4096) -> MappedNaturalRequest:
    zone_id, local_platter = divmod(platter_id, 800)
    local_level, slot = divmod(local_platter, 400)
    return MappedNaturalRequest(
        source_index=index,
        arrival_s=arrival_s,
        size_bytes=size_bytes,
        platter_id=platter_id,
        zone_id=zone_id,
        local_level=local_level,
        slot_in_half=slot,
    )


class NaturalTraceSkewTests(unittest.TestCase):
    def test_loader_keeps_reads_and_restores_timestamp_order(self) -> None:
        content = "\n".join(
            [
                "Timestamp,IOType,LUN,Offset,Size,Response",
                "3.0,R,0,300,4096,0.1",
                "1.0,W,0,100,4096,0.1",
                "2.0,R,0,200,8192,0.1",
                "1.5,R,0,150,4096,0.1",
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.csv"
            path.write_text(content + "\n", encoding="utf-8")
            requests, stats = load_sorted_read_requests(path, None)

        self.assertEqual([request.offset for request in requests], [150, 200, 300])
        self.assertEqual([request.arrival_s for request in requests], [0.0, 0.5, 1.5])
        self.assertEqual(stats["read_requests"], 3)
        self.assertGreater(stats["raw_out_of_order_adjacent_pairs"], 0)

    def test_count_and_time_windows_conserve_requests(self) -> None:
        requests = [
            _mapped(0, 0.0, 0),
            _mapped(1, 0.2, 1),
            _mapped(2, 1.1, 2),
            _mapped(3, 1.9, 3),
        ]

        counted = list(count_windows(requests, 3))
        timed = list(time_windows(requests, 1.0))

        self.assertEqual([len(window) for _, window in counted], [3, 1])
        self.assertEqual([index for index, _ in timed], [0, 1])
        self.assertEqual(sum(len(window) for _, window in counted), len(requests))
        self.assertEqual(sum(len(window) for _, window in timed), len(requests))

    def test_mapping_is_reproducible_and_contiguous_mapping_reaches_endpoints(self) -> None:
        config = _config()
        requests = [
            TraceRequest(index=0, arrival_s=0.0, io_type="R", lun=0, offset=1000, size_bytes=4096, observed_response_s=None),
            TraceRequest(index=1, arrival_s=1.0, io_type="R", lun=0, offset=2000, size_bytes=4096, observed_response_s=None),
            TraceRequest(index=2, arrival_s=2.0, io_type="R", lun=0, offset=3000, size_bytes=4096, observed_response_s=None),
        ]
        hashed = NaturalPlacementConfig("hash", "Hash", "randomized_hash", "hash", 11)
        contiguous = NaturalPlacementConfig("lba", "LBA", "contiguous_lba", "contiguous_lba")

        first = map_trace_requests(config, requests, hashed, 10, 30)
        second = map_trace_requests(config, requests, hashed, 10, 30)
        linear = map_trace_requests(config, requests, contiguous, 10, 30)

        self.assertEqual([request.platter_id for request in first], [request.platter_id for request in second])
        self.assertEqual([request.platter_id for request in linear], [0, 3199, 6399])

    def test_window_merge_preserves_bytes_and_reduces_task_count(self) -> None:
        config = _config()
        placement = config.placements[0]
        requests = [_mapped(0, 0.0, 10, 4096), _mapped(1, 0.1, 10, 8192), _mapped(2, 0.2, 11, 4096)]

        result = summarize_window(config, placement, "request_count", 3.0, 0, requests, False)

        self.assertEqual(result.row["logical_request_count"], 3)
        self.assertEqual(result.row["logical_bytes"], 16384)
        self.assertEqual(result.row["physical_task_count"], 2)
        self.assertAlmostEqual(result.row["requests_per_physical_task"], 1.5)

    def test_balanced_equal_cost_window_has_balanced_work_share(self) -> None:
        config = _config()
        requests = []
        for zone_id in range(config.zone_count):
            side = zone_id % 2
            slot = 0 if side == 0 else 399
            platter_id = zone_id * 800 + 400 + slot
            requests.append(_mapped(zone_id, float(zone_id), platter_id))

        result = summarize_window(
            config,
            config.placements[0],
            "request_count",
            float(len(requests)),
            0,
            requests,
            False,
        )

        self.assertAlmostEqual(result.row["max_zone_work_share"], 1 / config.zone_count)
        self.assertAlmostEqual(result.row["static_capacity_efficiency_proxy"], 1.0)
        self.assertAlmostEqual(result.row["work_jain_fairness"], 1.0)


if __name__ == "__main__":
    unittest.main()
