"""One physical partition, one reader, multiple shuttles and finite staging.

Controlled queueing/transport model, not a measured Silica digital twin.
Each rack lane and each connector segment is exclusive only during traversal.
Zone and Non-Zone use the SAME transport and shared reader ingress rules.
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import asdict, dataclass
import hashlib
import heapq
import json
import math
import random
from statistics import mean
from typing import Any


@dataclass(frozen=True)
class Config:
    rows: int = 8
    slots_per_row: int = 80
    length_m: float = 32.0
    shuttles: int = 4
    buffer_slots: int = 4
    policy: str = "nonzone_fifo"
    speed_m_s: float = 2.0
    acceleration_m_s2: float = 2.0
    connector_step_s: float = 3.0
    alignment_s: float = 0.5
    ingress_s: float = 1.0
    yield_penalty_s: float = 0.0
    contention_hold_s: float = 0.0
    pick_s: float = 1.0
    place_s: float = 1.0
    handoff_s: float = 1.0
    load_mount_s: float = 2.0
    read_s: float = 8.0
    unload_s: float = 1.0
    output_slots: int = 8
    docking_bays: int = 8
    lookahead: int = 16
    aging_s: float = 120.0

    def validate(self):
        if self.rows != 8 or not isinstance(self.shuttles, int) or not 1 <= self.shuttles <= 32:
            raise ValueError("Eight physical rack rows; 1-32 shuttles")
        if self.policy not in ("zone", "nonzone_fifo", "nonzone_local"):
            raise ValueError("Unknown policy")
        # Zone splits the eight rows evenly, so only divisors of the row count apply.
        if self.policy == "zone" and self.shuttles not in (1, 2, 4, 8):
            raise ValueError("Zone ownership requires 1/2/4/8 shuttles (even contiguous row split)")
        for name in ("buffer_slots", "output_slots", "docking_bays", "slots_per_row", "lookahead"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < (0 if name == "buffer_slots" else 1):
                raise ValueError(f"Invalid {name}")
        if self.docking_bays < self.shuttles:
            raise ValueError("This model provisions docking bays for the whole fleet")
        for name, value in asdict(self).items():
            if not isinstance(value, float):
                continue
            if not math.isfinite(value) or (value <= 0 and name not in ("yield_penalty_s", "contention_hold_s")):
                raise ValueError(f"Invalid {name}")
        if self.yield_penalty_s < 0 or self.contention_hold_s < 0:
            raise ValueError("yield_penalty_s and contention_hold_s must be nonnegative")

    @property
    def cycle_s(self):
        return self.load_mount_s + self.read_s + self.unload_s

    def home(self, platter):
        row, slot = divmod(platter, self.slots_per_row)
        return (row, (slot + .5) / self.slots_per_row * self.length_m)

    def owner(self, platter):
        return (platter // self.slots_per_row) * self.shuttles // self.rows


@dataclass(frozen=True)
class Request:
    index: int
    arrival_s: float
    platter: int


def make_requests(config, count, seed, pattern="uniform", rate=None):
    if pattern not in ("uniform", "hotspot") or count < 1 or (rate is not None and rate <= 0):
        raise ValueError("Invalid workload")
    location = random.Random(seed)
    timing = random.Random(seed + 1000003)
    requests, now = [], 0.0
    for i in range(count):
        if rate is not None:
            now += timing.expovariate(rate)
        draw, slot = location.random(), location.randrange(config.slots_per_row)
        # Hotspot is a controlled static address skew, not an observed Azure property.
        if pattern == "hotspot":
            row = int(draw / .75 * 2) if draw < .75 else 2 + min(5, int((draw - .75) / .25 * 6))
        else:
            row = min(7, int(draw * 8))
        requests.append(Request(i, now, row * config.slots_per_row + slot))
    return requests


def quantile(values, q):
    v = sorted(values)
    x = (len(v) - 1) * q
    i = int(x)
    return v[i] + (v[min(i + 1, len(v) - 1)] - v[i]) * (x - i)


class Rail:
    """No-wait paths with upstream docking; resource calendars allow gap reuse.

    Local horizontal lane blocks + seven separate vertical connector blocks +
    one reader approach block. Reader gate waiting uses finite docking bays,
    not rail occupancy. Endpoint bay microgeometry is an explicit abstraction.
    """
    READER = (-1, 0.0)

    def __init__(self, config):
        self.c = config
        self.calendars: dict[str, list[tuple[float, float]]] = {}
        self.records: list[dict[str, Any]] = []
        self.queries = self.checks = self.contended_steps = 0

    def horizontal(self, distance):
        if distance < 1e-10:
            return 0.0
        v, a = self.c.speed_m_s, self.c.acceleration_m_s2
        return (2 * math.sqrt(distance / a) if distance <= v*v/a else distance/v + v/a) + self.c.alignment_s

    def path(self, source, target):
        steps = []
        sr, sx = source
        tr, tx = target
        if source == target:
            return steps
        if sr == -1:
            steps.append(("reader_approach", self.c.ingress_s))
            sr, sx = 3, 0.0
        target_reader = tr == -1
        if target_reader:
            tr, tx = 3, 0.0
        if sr == tr:
            duration = self.horizontal(abs(tx - sx))
            if duration:
                steps.append((f"rack_lane_{sr}", duration))
        else:
            if sx > 0:
                steps.append((f"rack_lane_{sr}", self.horizontal(sx)))
            direction = 1 if tr > sr else -1
            row = sr
            while row != tr:
                steps.append((f"connector_{min(row, row + direction)}", self.c.connector_step_s))
                row += direction
            if tx > 0:
                steps.append((f"rack_lane_{tr}", self.horizontal(tx)))
        if target_reader:
            steps.append(("reader_approach", self.c.ingress_s))
        return steps

    def estimate(self, source, target, now):
        """Earliest conflict-free departure; returns (start, end, steps, contended_steps).

        contention_hold_s models stop-and-go yielding ON the contested block:
        every earlier reservation (vehicle) that blocks a step adds one
        stop-and-go to that step, so the shared block stays occupied longer.
        The cost grows with the number of vehicles queued for the block, which
        lets block capacity fall as density rises (accordion effect).
        Zero reproduces the original free-flow reservations.
        """
        self.queries += 1
        base = self.path(source, target)
        hold = self.c.contention_hold_s
        blockers: dict[int, set[tuple[float, float]]] = {}
        start = now
        encountered_contention = False
        penalty_applied = False
        for _ in range(10000):
            steps = [(r, d + hold * len(blockers.get(i, ()))) for i, (r, d) in enumerate(base)]
            offset, delay = 0.0, 0.0
            for i, (resource, duration) in enumerate(steps):
                a, b = start + offset, start + offset + duration
                calendar = self.calendars.get(resource, [])
                index = bisect_left(calendar, (a, -math.inf))
                for j in (index - 1, index):
                    if 0 <= j < len(calendar):
                        self.checks += 1
                        lo, hi = calendar[j]
                        if lo < b - 1e-9 and hi > a + 1e-9:
                            encountered_contention = True
                            delay = max(delay, hi - a + 1e-8)
                            if hold:
                                blockers.setdefault(i, set()).add((lo, hi))
                offset += duration
            if delay == 0:
                # Safety reservation delays the route until resources are free.
                # This optional extra delay models braking/yield/replanning work;
                # it is deliberately a controlled sensitivity parameter, not a
                # measured collision count or a calibrated hardware constant.
                if encountered_contention and not penalty_applied:
                    start += self.c.yield_penalty_s
                    penalty_applied = True
                    # The added yield delay may move the route into a later
                    # reservation. Recheck instead of returning a schedule
                    # that was only safe before the penalty was inserted.
                    continue
                return start, start + offset, steps, sum(len(v) for v in blockers.values())
            start += delay
        raise RuntimeError("Route planning did not converge")

    def reserve(self, source, target, now, sid, jid, phase):
        start, end, steps, contended = self.estimate(source, target, now)
        self.contended_steps += contended
        at = start
        for resource, duration in steps:
            calendar = self.calendars.setdefault(resource, [])
            interval = (at, at + duration)
            calendar.insert(bisect_left(calendar, interval), interval)
            self.records.append(dict(resource=resource, start_s=at, end_s=at + duration,
                                     shuttle=sid, request=jid, phase=phase))
            at += duration
        return start, end

    def validate(self):
        for resource, intervals in self.calendars.items():
            if any(b[0] < a[1] - 1e-7 for a, b in zip(intervals, intervals[1:])):
                raise RuntimeError(f"Rail overlap: {resource}")


class PartitionSimulation:
    def __init__(self, config: Config, requests: list[Request]):
        config.validate()
        if not requests or [r.index for r in requests] != list(range(len(requests))):
            raise ValueError("Requests need consecutive IDs")
        if any(not math.isfinite(r.arrival_s) or r.arrival_s < 0 or not 0 <= r.platter < config.rows*config.slots_per_row for r in requests):
            raise ValueError("Invalid request values")
        if any(a.arrival_s > b.arrival_s for a, b in zip(requests, requests[1:])):
            raise ValueError("Requests must be arrival sorted")
        self.c, self.requests = config, requests
        self.clock = requests[0].arrival_s
        self.shuttles = [dict(id=i, position=Rail.READER, idle=True) for i in range(config.shuttles)]
        self.rail = Rail(config)
        self.events, self.serial = [], 0
        self.pending, self.waiting, self.inbox, self.output = [], [], [], []
        self.away, self.jobs, self.timeline = set(), {}, []
        self.reader_state, self.reader_job = "idle", None
        self.gate_busy = False
        self.returned = 0
        self.max_input = self.max_output = self.max_dock = 0
        self.input_slot_time = self.reader_idle_demand = self.restricted_idle = 0.0
        self.pair_evaluations = 0
        self.reader_busy_s = 0.0
        self.last_read_s = self.last_unload_s = self.clock
        for r in requests:
            self.push(r.arrival_s, "arrival", r.index)

    def push(self, when, kind, payload):
        if when < self.clock - 1e-7:
            raise RuntimeError("Event in past")
        self.serial += 1
        heapq.heappush(self.events, (when, self.serial, kind, payload))

    def log(self, resource, phase, start, end, jid):
        if end > start + 1e-10:
            self.timeline.append(dict(resource=resource, phase=phase, start_s=start, end_s=end, request=jid))

    def eligible(self, sid, platter):
        return self.c.policy != "zone" or sid == self.c.owner(platter)

    def move(self, sid, jid, target, phase, event):
        shuttle, job = self.shuttles[sid], self.jobs[jid]
        start, end = self.rail.reserve(shuttle["position"], target, self.clock, sid, jid, phase)
        job["movement_s"] += end - start
        job["traffic_wait_s"] += start - self.clock
        self.log(f"S{sid}", "traffic_wait", self.clock, start, jid)
        self.log(f"S{sid}", phase, start, end, jid)
        self.push(end, event, (sid, jid, target))

    def dispatch(self):
        changed = False
        for jid in list(self.output):
            job = self.jobs[jid]
            if job["return_assigned"]:
                continue
            options = [s for s in self.shuttles if s["idle"] and self.eligible(s["id"], job["platter"])]
            if not options:
                continue
            shuttle = min(options, key=lambda s: (self.rail.estimate(s["position"], Rail.READER, self.clock)[1], s["id"]))
            shuttle["idle"] = False
            job["return_assigned"] = True
            self.move(shuttle["id"], jid, Rail.READER, "to_output", "at_output")
            changed = True
        while True:
            idle = [s for s in self.shuttles if s["idle"]]
            feasible = [i for i in self.pending if self.requests[i].platter not in self.away
                        and any(self.eligible(s["id"], self.requests[i].platter) for s in idle)]
            if not feasible:
                break
            candidates = feasible[:1]
            if self.c.policy == "nonzone_local" and self.clock - self.requests[feasible[0]].arrival_s < self.c.aging_s:
                candidates = feasible[:self.c.lookahead]
            options = []
            for jid in candidates:
                platter = self.requests[jid].platter
                for s in idle:
                    if not self.eligible(s["id"], platter):
                        continue
                    self.pair_evaluations += 1
                    pickup = self.rail.estimate(s["position"], self.c.home(platter), self.clock)[1] + self.c.pick_s
                    finish = self.rail.estimate(self.c.home(platter), Rail.READER, pickup)[1]
                    options.append((finish, self.requests[jid].arrival_s, jid, s["id"]))
            _, _, jid, sid = min(options)
            r = self.requests[jid]
            self.pending.remove(jid)
            self.away.add(r.platter)
            self.shuttles[sid]["idle"] = False
            self.jobs[jid] = dict(request=jid, platter=r.platter, shuttle=sid, arrival_s=r.arrival_s,
                                  dispatch_s=self.clock, movement_s=0.0, traffic_wait_s=0.0,
                                  delivery_wait_s=0.0, output_block_s=0.0, return_assigned=False,
                                  ready=False, read_done_s=None, returned_s=None)
            self.move(sid, jid, self.c.home(r.platter), "fetch", "at_platter")
            changed = True
        return changed

    def start_read(self, jid):
        self.reader_state, self.reader_job = "read", jid
        job = self.jobs[jid]
        job["read_start_s"] = self.clock
        duration = self.c.load_mount_s + self.c.read_s
        self.reader_busy_s += duration
        self.log("Reader", "load_read", self.clock, self.clock + duration, jid)
        self.push(self.clock + duration, "read_done", jid)

    def pump(self):
        changed = False
        if self.reader_state == "blocked" and len(self.output) < self.c.output_slots:
            jid = self.reader_job
            job = self.jobs[jid]
            job["output_block_s"] = self.clock - job["read_done_s"]
            self.log("Reader", "output_block", job["read_done_s"], self.clock, jid)
            self.reader_state = "unload"
            self.reader_busy_s += self.c.unload_s
            self.log("Reader", "unload", self.clock, self.clock + self.c.unload_s, jid)
            self.push(self.clock + self.c.unload_s, "unloaded", jid)
            changed = True
        if self.reader_state == "idle" and self.inbox and self.jobs[self.inbox[0]]["ready"]:
            self.start_read(self.inbox.pop(0))
            changed = True
        if not self.gate_busy and self.waiting:
            kind, sid, jid = self.waiting[0]
            can_enter = (kind == "return" or
                         (self.c.buffer_slots == 0 and self.reader_state == "idle") or
                         (self.c.buffer_slots > 0 and len(self.inbox) < self.c.buffer_slots))
            if can_enter:
                self.waiting.pop(0)
                self.gate_busy = True
                job = self.jobs[jid]
                if kind == "deliver":
                    job["admitted_s"] = self.clock
                    job["delivery_wait_s"] = self.clock - job["at_reader_s"]
                    self.log(f"S{sid}", "delivery_wait", job["at_reader_s"], self.clock, jid)
                    if self.c.buffer_slots:
                        self.inbox.append(jid)
                    else:
                        self.reader_state, self.reader_job = "handoff", jid
                    duration, event = self.c.handoff_s, "handed_off"
                else:
                    self.log(f"S{sid}", "output_pick_wait", job["return_at_s"], self.clock, jid)
                    duration, event = self.c.pick_s, "return_picked"
                self.log(f"S{sid}", "handoff" if kind == "deliver" else "output_pick", self.clock, self.clock + duration, jid)
                self.log("Gate", kind, self.clock, self.clock + duration, jid)
                self.push(self.clock + duration, event, (sid, jid))
                changed = True
        self.max_input = max(self.max_input, len(self.inbox))
        self.max_output = max(self.max_output, len(self.output))
        self.max_dock = max(self.max_dock, len(self.waiting) + int(self.gate_busy))
        if self.max_input > self.c.buffer_slots or self.max_output > self.c.output_slots or self.max_dock > self.c.docking_bays:
            raise RuntimeError("Finite staging capacity exceeded")
        return changed

    def handle(self, kind, payload):
        if kind == "arrival":
            self.pending.append(payload)
        elif kind in ("at_platter", "at_reader", "at_output", "at_home"):
            sid, jid, target = payload
            self.shuttles[sid]["position"] = target
            if kind == "at_platter":
                self.log(f"S{sid}", "pick", self.clock, self.clock + self.c.pick_s, jid)
                self.push(self.clock + self.c.pick_s, "picked", (sid, jid))
            elif kind == "at_reader":
                self.jobs[jid]["at_reader_s"] = self.clock
                self.waiting.append(("deliver", sid, jid))
            elif kind == "at_output":
                self.jobs[jid]["return_at_s"] = self.clock
                # Fixed return priority at the shared gate avoids circular blocking.
                index = next((i for i, v in enumerate(self.waiting) if v[0] == "deliver"), len(self.waiting))
                self.waiting.insert(index, ("return", sid, jid))
            else:
                self.log(f"S{sid}", "place", self.clock, self.clock + self.c.place_s, jid)
                self.push(self.clock + self.c.place_s, "returned", (sid, jid))
        elif kind == "picked":
            sid, jid = payload
            self.move(sid, jid, Rail.READER, "delivery", "at_reader")
        elif kind == "handed_off":
            sid, jid = payload
            self.gate_busy = False
            self.shuttles[sid]["idle"] = True
            self.jobs[jid]["ready"] = True
            self.jobs[jid]["handoff_done_s"] = self.clock
            if self.c.buffer_slots == 0:
                self.start_read(jid)
        elif kind == "read_done":
            self.jobs[payload]["read_done_s"] = self.clock
            self.last_read_s = self.clock
            self.reader_state = "blocked"
        elif kind == "unloaded":
            self.output.append(payload)
            self.last_unload_s = self.clock
            self.reader_state, self.reader_job = "idle", None
        elif kind == "return_picked":
            sid, jid = payload
            self.gate_busy = False
            self.output.remove(jid)
            self.move(sid, jid, self.c.home(self.jobs[jid]["platter"]), "return", "at_home")
        elif kind == "returned":
            sid, jid = payload
            self.jobs[jid]["returned_s"] = self.clock
            self.away.remove(self.jobs[jid]["platter"])
            self.shuttles[sid]["idle"] = True
            self.returned += 1
        else:
            raise RuntimeError(f"Unknown event {kind}")

    def integrate(self, dt):
        self.input_slot_time += len(self.inbox) * dt
        if self.reader_state == "idle" and (self.pending or any(j["read_done_s"] is None for j in self.jobs.values())):
            self.reader_idle_demand += dt
        ready = [self.requests[i].platter for i in self.pending if self.requests[i].platter not in self.away]
        for s in self.shuttles:
            if s["idle"] and ready and not any(self.eligible(s["id"], p) for p in ready):
                self.restricted_idle += dt

    def run(self):
        iterations = 0
        while self.events:
            at = self.events[0][0]
            self.integrate(at - self.clock)
            self.clock = at
            while self.events and self.events[0][0] <= at + 1e-10:
                _, _, kind, payload = heapq.heappop(self.events)
                self.handle(kind, payload)
            while True:
                changed = self.pump()
                changed = self.dispatch() or changed
                if not changed:
                    break
            iterations += 1
            if iterations > 100 * len(self.requests):
                raise RuntimeError("No progress")
        if self.returned != len(self.requests) or self.pending or self.away or self.inbox or self.output or self.waiting:
            raise RuntimeError(f"Incomplete or deadlocked run: {self.returned}/{len(self.requests)}")
        self.rail.validate()
        by_resource = {}
        for row in self.timeline:
            by_resource.setdefault(row["resource"], []).append(row)
        for resource, rows in by_resource.items():
            rows.sort(key=lambda r: r["start_s"])
            if any(b["start_s"] < a["end_s"] - 1e-7 for a, b in zip(rows, rows[1:])):
                raise RuntimeError(f"Service overlap {resource}")
        jobs = [self.jobs[i] for i in range(len(self.requests))]
        lats = [j["read_done_s"] - j["arrival_s"] for j in jobs]
        phase_fields = [("queue_mean_s", "arrival_s", "dispatch_s"),
                        ("fetch_delivery_mean_s", "dispatch_s", "at_reader_s"),
                        ("delivery_wait_mean_s", "at_reader_s", "admitted_s"),
                        ("handoff_mean_s", "admitted_s", "handoff_done_s"),
                        ("buffer_wait_mean_s", "handoff_done_s", "read_start_s"),
                        ("load_read_mean_s", "read_start_s", "read_done_s")]
        for job in jobs:
            times = [job[k] for k in ("arrival_s", "dispatch_s", "at_reader_s", "admitted_s", "handoff_done_s", "read_start_s", "read_done_s", "returned_s")]
            if any(b < a - 1e-7 for a, b in zip(times, times[1:])):
                raise RuntimeError("Causality violation")
        span = self.last_unload_s - self.requests[0].arrival_s
        result = dict(requests=len(jobs), returned=self.returned, p99_s=quantile(lats, .99), mean_s=mean(lats),
                      read_span_s=self.last_read_s-self.requests[0].arrival_s, drain_span_s=self.clock-self.requests[0].arrival_s,
                      throughput_req_s=len(jobs)/(self.last_read_s-self.requests[0].arrival_s),
                      reader_busy_fraction=self.reader_busy_s/span,
                      reader_optical_fraction=len(jobs)*self.c.read_s/span,
                      reader_idle_demand_s=self.reader_idle_demand, restricted_idle_s=self.restricted_idle,
                      input_occupancy_s=self.input_slot_time, max_input=self.max_input, max_output=self.max_output,
                      max_dock=self.max_dock, pair_evaluations=self.pair_evaluations,
                      route_queries=self.rail.queries, reservation_checks=self.rail.checks,
                      contended_steps=self.rail.contended_steps)
        prefetch_leads = [j['read_start_s'] - j['handoff_done_s'] for j in jobs if j['read_start_s'] - j['handoff_done_s'] > 1e-8]
        result['prefetch_hit_fraction'] = len(prefetch_leads) / len(jobs)
        result['prefetch_lead_mean_s'] = mean(prefetch_leads) if prefetch_leads else 0.0
        result['route_motion_s'] = sum(float(r['end_s']) - float(r['start_s']) for r in self.rail.records if r['phase'] in {'fetch', 'delivery', 'return'})
        for metric in ("movement_s", "traffic_wait_s", "delivery_wait_s", "output_block_s"):
            result[metric] = sum(j[metric] for j in jobs)
        for name, start, end in phase_fields:
            result[name] = mean(j[end]-j[start] for j in jobs)
        if not math.isclose(sum(result[n] for n, _, _ in phase_fields), result["mean_s"], abs_tol=1e-7):
            raise RuntimeError("Latency accounting error")
        if not 0 <= result["reader_busy_fraction"] <= 1 + 1e-9:
            raise RuntimeError("Reader utilization outside bounds")
        result["workload_sha256"] = hashlib.sha256(json.dumps([asdict(r) for r in self.requests], sort_keys=True).encode()).hexdigest()
        return result, jobs, self.timeline
