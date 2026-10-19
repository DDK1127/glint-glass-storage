"""Probe: Non-Zone vs Zone with perfect (conflict-free) paths, the ceiling for any path planner such as CBS."""
import sys; from pathlib import Path; sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dataclasses import replace
from statistics import median
from collections import defaultdict
import numpy as np
from glass_sim import systor17 as S
from glass_sim import io_scheduler as IO
from glass_sim.partition_feeder_study import Rail

class FreeRail(Rail):
    """Perfect traffic: every path is conflict-free (vehicles never block each other)."""
    def estimate(self, source, target, now):
        self.queries += 1
        steps = self.path(source, target)
        return now, now + sum(d for _, d in steps), steps, 0
    def reserve(self, source, target, now, sid, jid, phase):
        start, end, steps, _ = self.estimate(source, target, now)
        at = start
        for r, d in steps:
            self.records.append(dict(resource=r, start_s=at, end_s=at + d, shuttle=sid, request=jid, phase=phase)); at += d
        return start, end
    def validate(self): pass

def util(sim, T):
    busy = defaultdict(float)
    for r in sim.rail.records: busy[r['resource'].rsplit('_',1)[0] if r['resource'].startswith(('rack_lane','connector')) else r['resource']] += r['end_s']-r['start_s']
    n = {'rack_lane':8,'connector':7,'reader_approach':1}
    return {k: busy[k]/(T*n[k]) for k in n}

def runset(c, wins, scale_fn, free=False):
    out=[]
    for rt,pl,sz in wins:
        sim=IO.IOSimulation(c,S.to_requests(rt,pl,sz,scale_fn(rt)),IO.SilicaFIFO())
        if free: sim.rail=FreeRail(c)
        s=sim.run(); out.append((s, util(sim, sim.clock)))
    return out

if __name__=='__main__':
    d=S.load('20160222')
    for p in ('contig_1tb','contig_balanced'):
        plat=S.PLACEMENTS[p](d,640,seed=1); rng=np.random.default_rng(1)
        wins=[S.sample(d,plat,S.day_start_hour(d,h),600,2000,rng) for h in (8,9,10,11,12,13)]
        c=replace(IO.IOConfig(),request_overhead_s=0.25)
        cap=median(2000/IO.IOSimulation(c,S.to_requests(*w),IO.SilicaFIFO()).run()['makespan_s'] for w in wins)
        sf=lambda rt:(2000/(cap*.75))/rt[-1]
        for label,disp,free in (('Zone','zone',False),('Non-Zone (now)','nonzone',False),('Non-Zone, perfect paths','nonzone',True),('Zone, perfect paths','zone',True)):
            res=runset(replace(c,dispatch=disp),wins,sf,free)
            m=lambda k: median(r[0][k] for r in res); u=lambda k: median(r[1][k] for r in res)
            print(f"{p:16s} {label:24s} mean {m('mean_s'):5.0f} p99 {m('p99_s'):5.0f} reader starved {m('reader_starved_fraction'):.0%} | busy: reader entrance {u('reader_approach'):.0%} connector {u('connector'):.0%} lane {u('rack_lane'):.0%}")

def per_block(sim, T):
    b = defaultdict(float)
    for r in sim.rail.records: b[r['resource']] += r['end_s'] - r['start_s']
    return {k: v / T for k, v in b.items()}

def overlap(sim):
    """Peak number of shuttles that the perfect-path run puts on one block at once."""
    ev = defaultdict(list)
    for r in sim.rail.records: ev[r['resource']] += [(r['start_s'], 1), (r['end_s'], -1)]
    peak = {}
    for k, e in ev.items():
        cur = m = 0
        for _, x in sorted(e, key=lambda z: (z[0], z[1])): cur += x; m = max(m, cur)
        peak[k] = m
    return peak
