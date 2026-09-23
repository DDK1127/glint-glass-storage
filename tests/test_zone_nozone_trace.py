from pathlib import Path
import tempfile
import unittest
from dataclasses import replace

from glass_sim.zone_nozone_trace import Read, simulate
from glass_sim.zone_nozone_comparison import NO_ZONE, NO_ZONE_VIRTUAL, STATIC_ZONE
from tests.test_zone_nozone_comparison import config


class TraceTests(unittest.TestCase):
    def test_late_request_is_not_served_early(self):
        with tempfile.TemporaryDirectory() as d:
            c=config(Path(d))
            reads=[Read(0,0,("a","v"),1024),Read(1,100,("a","v"),1024)]
            for policy in (STATIC_ZONE,NO_ZONE):
                s,j,_,r=simulate(reads,{("a","v"):0},{0:(0,2,.5)},c,policy)
                self.assertEqual(len(j),2)
                self.assertGreaterEqual(j[1]["start_s"],100)
                self.assertGreater(r[1]["read_done_s"],100)
                self.assertEqual(s["logical_bytes"],2048)

    def test_only_arrived_reads_are_merged(self):
        with tempfile.TemporaryDirectory() as d:
            c=config(Path(d))
            reads=[Read(0,0,("a","v"),1024),Read(1,0,("a","v"),1024),Read(2,.1,("a","v"),1024)]
            s,j,_,r=simulate(reads,{("a","v"):0},{0:(0,2,.5)},c,STATIC_ZONE)
            self.assertEqual([x["merge_requests"] for x in j],[2,1])
            self.assertEqual(s["physical_bytes"],2048)
            self.assertEqual(s["logical_bytes"],3072)

    def test_future_shuttle_state_not_used_as_idle(self):
        with tempfile.TemporaryDirectory() as d:
            c=config(Path(d))
            reads=[Read(i,float(i), (str(i),"v"),1024) for i in range(12)]
            mapped={r.key:r.index for r in reads}
            positions={i:(0,2+(i%2),.5) for i in range(12)}
            a=simulate(reads,mapped,positions,c,NO_ZONE)
            b=simulate(reads,mapped,positions,c,NO_ZONE)
            self.assertEqual(a[1:],b[1:])
            self.assertEqual(len(a[3]),12)
            for row in a[3]: self.assertGreaterEqual(row["read_done_s"],row["arrival_s"])

    def test_platter_cannot_be_fetched_twice_concurrently(self):
        with tempfile.TemporaryDirectory() as d:
            c=config(Path(d))
            reads=[Read(0,0,("a","v"),1024),Read(1,.1,("a","v"),1024)]
            _,jobs,_,_=simulate(reads,{("a","v"):0},{0:(0,2,.5)},c,NO_ZONE)
            self.assertEqual(len(jobs),2)
            self.assertGreaterEqual(jobs[1]["start_s"],jobs[0]["end_s"])

    def test_phase_breakdown_and_zone_tail_are_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            c=config(Path(d))
            reads=[Read(i,0,(str(i),"v"),1024) for i in range(8)]
            mapped={r.key:r.index for r in reads}
            positions={i:(i//4,2+(i%2),.5+(i%4)) for i in range(8)}
            summary,jobs,_,requests=simulate(reads,mapped,positions,c,NO_ZONE)
            self.assertGreaterEqual(summary["zone_completion_spread_s"],0)
            self.assertTrue(all("zone_id" in row for row in requests))
            self.assertAlmostEqual(
                summary["conflict_wait_s"]+summary["detour_s"],
                summary["fetch_coordination_s"]
                +summary["pick_coordination_s"]
                +summary["delivery_coordination_s"]
                +summary["reader_coordination_s"]
                +summary["return_coordination_s"]
                +summary["place_coordination_s"],
                places=6,
            )
            self.assertAlmostEqual(
                summary["latency_mean_s"],
                summary["request_queue_mean_s"]
                +summary["request_fetch_mean_s"]
                +summary["request_pick_mean_s"]
                +summary["request_delivery_mean_s"]
                +summary["request_reader_queue_mean_s"]
                +summary["request_reader_read_mean_s"]
                +summary["request_coordination_mean_s"],
                places=6,
            )

    def test_virtual_no_zone_is_reproducible_and_has_no_collision_cost(self):
        with tempfile.TemporaryDirectory() as d:
            c=config(Path(d))
            reads=[Read(i,float(i), (str(i),"v"),1024) for i in range(12)]
            mapped={r.key:r.index for r in reads}
            positions={i:(i//6,2+(i%2),.5+(i%4)) for i in range(12)}
            first=simulate(reads,mapped,positions,c,NO_ZONE_VIRTUAL)
            second=simulate(reads,mapped,positions,c,NO_ZONE_VIRTUAL)

        first_summary=dict(first[0])
        second_summary=dict(second[0])
        first_summary.pop("cpu_wall_s")
        second_summary.pop("cpu_wall_s")
        self.assertEqual(first_summary,second_summary)
        self.assertEqual(first[1:],second[1:])
        self.assertEqual(first[0]["conflict_wait_s"],0)
        self.assertEqual(first[0]["detour_s"],0)
