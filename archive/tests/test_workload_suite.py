from __future__ import annotations

import unittest

from glass_v2.panel_static_zone import PanelStaticZoneSimulator, merge_panel_requests
from glass_v2.workload_suite import (
    WorkloadCaseConfig,
    build_rank_to_platter_map,
    generate_workload_requests,
    sample_zipf_ranks,
)
from tests.test_panel_static_zone import _config


class WorkloadSuiteTests(unittest.TestCase):
    def test_random_rank_placement_is_a_permutation(self) -> None:
        mapping = build_rank_to_platter_map(6400, "random", 17)

        self.assertEqual(len(mapping), 6400)
        self.assertEqual(set(mapping), set(range(6400)))

    def test_clustered_rank_placement_packs_hottest_glasses_in_zone_zero(self) -> None:
        mapping = build_rank_to_platter_map(6400, "clustered", 17)

        self.assertEqual(mapping[:800], list(range(800)))

    def test_zipf_random_and_clustered_use_the_same_rank_sequence(self) -> None:
        first = sample_zipf_ranks(6400, 1.3, 1000, 19)
        second = sample_zipf_ranks(6400, 1.3, 1000, 19)

        self.assertEqual(first, second)

    def test_zipf_placement_changes_locations_not_merge_cardinality(self) -> None:
        random_case = WorkloadCaseConfig(
            name="random",
            display_name="Random",
            family="zipf",
            generator="zipf",
            zipf_alpha=1.3,
            rank_placement="random",
        )
        clustered_case = WorkloadCaseConfig(
            name="clustered",
            display_name="Clustered",
            family="zipf",
            generator="zipf",
            zipf_alpha=1.3,
            rank_placement="clustered",
        )
        random_requests = generate_workload_requests(
            PanelStaticZoneSimulator(_config(batch_size=1000)),
            random_case,
            1000,
            64 * 1024**2,
            0,
            23,
        )
        clustered_requests = generate_workload_requests(
            PanelStaticZoneSimulator(_config(batch_size=1000)),
            clustered_case,
            1000,
            64 * 1024**2,
            0,
            23,
        )

        random_merged = merge_panel_requests(random_requests)
        clustered_merged = merge_panel_requests(clustered_requests)
        self.assertEqual(len(random_merged), len(clustered_merged))
        self.assertEqual(
            sorted(request.merged_request_count for request in random_merged),
            sorted(request.merged_request_count for request in clustered_merged),
        )
        self.assertEqual(sum(request.size_bytes for request in random_merged), 1000 * 64 * 1024**2)

    def test_uniform_scan_balances_logical_requests_across_zones(self) -> None:
        case = WorkloadCaseConfig(
            name="scan",
            display_name="Scan",
            family="uniform",
            generator="uniform_scan",
        )
        requests = generate_workload_requests(
            PanelStaticZoneSimulator(_config(batch_size=1000)),
            case,
            1000,
            64 * 1024**2,
            0,
            29,
        )
        zone_counts = [sum(request.zone_id == zone for request in requests) for zone in range(8)]

        self.assertEqual(zone_counts, [125] * 8)


if __name__ == "__main__":
    unittest.main()
