"""Probe: what if shuttles fetch before returning read platters (limited to queue room)?"""
import sys; from pathlib import Path; sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataclasses import replace
from statistics import median
import numpy as np, json
from glass_sim import systor17 as S
from glass_sim.io_scheduler import IOConfig, IOSimulation, SilicaFIFO
from queue_diagnosis import Diagnose, CFG, ROOT
if __name__=='__main__':
    d=S.load('20160222'); plat=S.PLACEMENTS[CFG['placement']](d,640,seed=1); rng=np.random.default_rng(1)
    wins=[S.sample(d,plat,S.day_start_hour(d,h),600,2000,rng) for h in CFG['sampling']['windows_start_hour']]
    base=replace(IOConfig(),request_overhead_s=1.0,buffer_slots=8)
    cap=median(2000/IOSimulation(base,S.to_requests(*w),SilicaFIFO()).run()['makespan_s'] for w in wins)
    for load,m in CFG['loads'].items():
        for pr in ('return_first','fetch_first'):
            res=[];dg=Diagnose()
            for rt,p,sz in wins:
                s=IOSimulation(replace(base,return_priority=pr),S.to_requests(rt,p,sz,(2000/(m*cap))/rt[-1]),SilicaFIFO(),observer=dg).run(); res.append(s)
            M=lambda k: median(r[k] for r in res)
            print(load,f"{pr:12s} mean {M('mean_s'):5.0f} p99 {M('p99_s'):5.0f} reader idle w/ pending {M('reader_starved_fraction'):.0%} queue empty {dg.queue_len[0]/dg.total:.0%} blocked {median(r['reader_blocked_s']/r['makespan_s'] for r in res):.1%}")
