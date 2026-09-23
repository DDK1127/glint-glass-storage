import json
from pathlib import Path
import unittest

from glass_sim.no_zone_conflict import Segment, close_intervals, replay, exposure
from glass_sim.azure_capacity_scalability import VirtualPlatterWork


class NoZoneTests(unittest.TestCase):
    def test_head_on_exact_window(self):
        a = Segment(0,0,0,"fetch",0,5,0,0,1)
        b = Segment(1,1,0,"fetch",0,5,5,0,-1)
        self.assertEqual(close_intervals(a,b,1,.5), [(2,3)])

    def test_following_and_stopped_occupancy(self):
        a = Segment(0,0,0,"fetch",0,5,0,0,2)
        b = Segment(1,1,0,"fetch",0,5,4,0,1)
        self.assertEqual(close_intervals(a,b,1,.5), [(3,5)])
        stopped = Segment(1,1,0,"pick",0,5,4,0)
        self.assertEqual(close_intervals(a,stopped,1,.5), [(1.5,2.5)])

    def test_different_side_or_clear_lane(self):
        a = Segment(0,0,0,"fetch",0,5,0,0,1)
        self.assertFalse(close_intervals(a,Segment(1,1,1,"fetch",0,5,0,0,1),1,.5))
        self.assertFalse(close_intervals(a,Segment(1,1,0,"fetch",0,5,0,1,1),1,.5))

    def test_accelerating_encounter(self):
        a = Segment(0,0,0,"fetch",0,3,0,0,0,0,2)
        b = Segment(1,1,0,"pick",0,3,4,0)
        interval = close_intervals(a,b,1,.5)[0]
        self.assertAlmostEqual(interval[0], 3**.5)
        self.assertAlmostEqual(interval[1], 5**.5)

    def test_replay_conservation_reproducibility(self):
        root = Path(__file__).resolve().parents[1]
        config = json.loads((root/"experiments/no-zone-conflict/full.json").read_text())
        work = [VirtualPlatterWork(i,i,1000*(i+1),2,1) for i in range(24)]
        result = replay(work,config,5,16)
        self.assertEqual(result,replay(work,config,5,16))
        segments,tasks,horizon = result
        self.assertEqual(len(tasks),24)
        self.assertEqual(sum(r["logical_requests"] for r in tasks),48)
        self.assertEqual(len({r["task"] for r in tasks}),24)
        self.assertTrue(horizon>0)
        self.assertEqual(exposure(segments,config),exposure(segments,config))
