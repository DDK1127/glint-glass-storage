from __future__ import annotations

from pathlib import Path
import unittest

from glass_sim.natural_trace_skew import (
    MappedNaturalRequest,
    NaturalPlacementConfig,
    NaturalTraceSkewConfig,
)
from glass_sim.natural_trace_static_ownership import (
    NaturalTraceStaticOwnershipConfig,
    simulate_static_window,
)
from glass_sim.panel_static_zone import (
    PanelGeometryConfig,
    PanelMovementConfig,
    PanelTimingConfig,
)


def _config() -> NaturalTraceStaticOwnershipConfig:
    natural = NaturalTraceSkewConfig(
        output_dir=Path("results/test-natural"),
        trace_path=Path("unused.csv"),
        max_read_requests=None,
        request_count_windows=(8,),
        time_windows_s=(1.0,),
        hotspot_work_share_threshold=0.25,
        primary_count_window=8,
        primary_time_window_s=1.0,
        heatmap_placement="hash",
        validation_sample_windows=1,
        stripe_bytes=64 * 1024 * 1024,
        platter_count=64,
        placements=(
            NaturalPlacementConfig(
                "hash",
                "Hash",
                "randomized_hash",
                "hash",
                7,
            ),
        ),
        geometry=PanelGeometryConfig(
            levels=8,
            zone_height_racks=2,
            half_panel_length_m=16.0,
            slots_per_half=4,
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
    return NaturalTraceStaticOwnershipConfig(
        output_dir=Path("results/test"),
        natural_trace_config_path=Path("unused.json"),
        max_read_requests=None,
        request_count_windows=(8,),
        time_windows_s=(1.0,),
        include_full_trace=True,
        natural_config=natural,
    )


def _request(index: int, zone: int, local: int) -> MappedNaturalRequest:
    local_level, slot = divmod(local, 4)
    return MappedNaturalRequest(
        source_index=index,
        arrival_s=float(index),
        size_bytes=4096,
        platter_id=zone * 8 + local,
        zone_id=zone,
        local_level=local_level,
        slot_in_half=slot,
    )


class NaturalTraceStaticOwnershipTests(unittest.TestCase):
    def test_balanced_window_retains_ideal_throughput(self) -> None:
        config = _config()
        requests = [
            _request(zone, zone, 4 if zone % 2 == 0 else 7)
            for zone in range(8)
        ]

        row = simulate_static_window(
            config,
            "hash",
            "Hash",
            "randomized_hash",
            "request_count",
            8.0,
            0,
            requests,
            False,
        )

        self.assertAlmostEqual(row["busiest_work_owner_share"], 0.125)
        self.assertAlmostEqual(row["throughput_retained_vs_ideal"], 1.0)
        self.assertAlmostEqual(row["throughput_loss_vs_ideal"], 0.0)

    def test_single_owner_window_retains_one_eighth_throughput(self) -> None:
        config = _config()
        requests = [_request(index, 0, index) for index in range(8)]

        row = simulate_static_window(
            config,
            "hash",
            "Hash",
            "randomized_hash",
            "request_count",
            8.0,
            0,
            requests,
            False,
        )

        self.assertAlmostEqual(row["busiest_work_owner_share"], 1.0)
        self.assertAlmostEqual(row["throughput_retained_vs_ideal"], 0.125)
        self.assertAlmostEqual(row["throughput_loss_vs_ideal"], 0.875)

    def test_window_local_merge_preserves_logical_count(self) -> None:
        config = _config()
        requests = [_request(0, 0, 0), _request(1, 0, 0)]

        row = simulate_static_window(
            config,
            "hash",
            "Hash",
            "randomized_hash",
            "request_count",
            2.0,
            0,
            requests,
            False,
        )

        self.assertEqual(row["logical_request_count"], 2)
        self.assertEqual(row["physical_task_count"], 1)
        self.assertEqual(row["requests_per_physical_task"], 2.0)


if __name__ == "__main__":
    unittest.main()
