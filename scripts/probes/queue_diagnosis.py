"""Probe: why is the reader-front queue empty when the reader is idle?

Whenever the reader is idle while requests are pending, look at the oldest pending
request and record where it is stuck; weight by time. Also records queue length
and what the shuttles are doing. Same setting as experiments/queue-cache-story.
"""
from collections import defaultdict
from dataclasses import replace
import json
from pathlib import Path
from statistics import median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np

from glass_sim import systor17 as S
from glass_sim.io_scheduler import IOConfig, IOSimulation, SilicaFIFO

ROOT = Path(__file__).resolve().parents[2]
CFG = json.loads((ROOT / "experiments/queue-cache-story/config.json").read_text())


class Diagnose:
    def __init__(self):
        self.stuck = defaultdict(float)     # where the oldest pending request is, while the reader idles
        self.queue_len = defaultdict(float)
        self.shuttle = defaultdict(float)   # shuttle-seconds by activity
        self.last_phase = {}
        self.seen = 0
        self.total = 0.0

    def phase(self, sim, sid):
        recs = sim.rail.records
        for r in recs[self.seen:]:
            self.last_phase[r["shuttle"]] = r["phase"]
        self.seen = len(recs)
        p = self.last_phase.get(sid)
        return "returning" if p in ("to_output", "return") else "fetching"

    def __call__(self, sim, dt):
        self.total += dt
        self.queue_len[min(len(sim.inbox), 8)] += dt
        gate = {tid for kind, _, tid in sim.waiting if kind == "deliver"}
        for s in sim.shuttles:
            if s["idle"]:
                act = "idle"
            elif any(w[1] == s["id"] for w in sim.waiting):
                act = "waiting at reader"
            else:
                act = self.phase(sim, s["id"])
            self.shuttle[act] += dt
        if sim.reader_state != "idle" or not (sim.queue or sim.unread):
            return
        # oldest pending request and where it is
        best, where = None, None
        for p, q in sim.queue.items():
            if q and (best is None or q[0] < best):
                best = q[0]
                if p in sim.away:
                    where = "platter still on its way home (just read)"
                else:
                    owner = sim.shuttles[sim.c.owner(p)]
                    where = ("platter at home, its shuttle idle" if owner["idle"] else
                             f"platter at home, its shuttle busy {self.phase(sim, owner['id'])}")
        for t in sim.trips:
            if t["read_done"] or t.get("from_cache"):
                continue
            first = min(t["requests"])
            if best is None or first < best:
                best = first
                where = "platter waiting at the reader gate" if t["trip"] in gate else "platter being fetched (shuttle on the way)"
        self.stuck[where] += dt


def main():
    d = S.load("20160222", root=ROOT / S.RAW)
    plat = S.PLACEMENTS[CFG["placement"]](d, IOConfig().platters, seed=CFG["seed"])
    rng = np.random.default_rng(CFG["seed"])
    sc = CFG["sampling"]
    wins = [S.sample(d, plat, S.day_start_hour(d, h), sc["span_s"], sc["requests"], rng) for h in sc["windows_start_hour"]]
    base = replace(IOConfig(), request_overhead_s=CFG["request_overhead_s"], buffer_slots=8)
    cap = median(len(w[0]) / IOSimulation(base, S.to_requests(*w), SilicaFIFO()).run()["makespan_s"] for w in wins)
    out = {}
    for load, m in CFG["loads"].items():
        agg = Diagnose()
        idle = 0.0
        for rel_t, p, size in wins:
            sim = IOSimulation(base, S.to_requests(rel_t, p, size, (len(rel_t) / (m * cap)) / rel_t[-1]), SilicaFIFO(), observer=agg)
            s = sim.run()
            idle += s["reader_starved_s"]
        stuck_total = sum(agg.stuck.values())
        out[load] = dict(
            reader_idle_with_pending_share=stuck_total / agg.total,
            stuck={k: v / stuck_total for k, v in sorted(agg.stuck.items(), key=lambda kv: -kv[1])},
            queue_length_share={k: agg.queue_len[k] / agg.total for k in sorted(agg.queue_len)},
            shuttle_activity={k: v / sum(agg.shuttle.values()) for k, v in sorted(agg.shuttle.items(), key=lambda kv: -kv[1])})
    print(json.dumps(out, indent=1, ensure_ascii=False))
    (ROOT / "results/queue-cache-story/queue_diagnosis.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
