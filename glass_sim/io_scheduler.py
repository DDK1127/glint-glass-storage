"""Glass-library I/O scheduling simulator: one reader, Zone shuttles, pluggable schedulers.

Controlled model for studying *which platter to fetch next*; not a Silica digital twin.
The unit of transport is a trip: one platter visit to the reader that may serve
several queued requests (Silica SOSP'23 §4.1: once a platter is in the drive,
all its queued requests are served). Rail physics and reservations are reused
from partition_feeder_study so transport behaviour matches earlier studies.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict, dataclass
import hashlib
import heapq
import json
import math
import random
from statistics import mean
import time
from typing import Any

from glass_sim.partition_feeder_study import Rail, quantile

MiB = 1024 ** 2
GiB = 1024 ** 3


@dataclass(frozen=True)
class IOConfig:
    rows: int = 8
    slots_per_row: int = 80
    length_m: float = 32.0
    shuttles: int = 8
    buffer_slots: int = 8
    output_slots: int = 8
    docking_bays: int = 8
    # Rail physics (same names and defaults as partition_feeder_study.Config).
    speed_m_s: float = 2.0
    acceleration_m_s2: float = 2.0
    connector_step_s: float = 3.0
    alignment_s: float = 0.5
    ingress_s: float = 1.0
    yield_penalty_s: float = 0.0
    contention_hold_s: float = 0.5
    pick_s: float = 1.0
    place_s: float = 1.0
    handoff_s: float = 1.0
    # Reader. Silica drives scale in multiples of 30 MB/s (SOSP'23 §3); per-request
    # overhead (XY seek + focus + track scan setup) is an assumption.
    load_mount_s: float = 2.0
    unload_s: float = 1.0
    read_mb_s: float = 30.0
    request_overhead_s: float = 1.0
    # Platter cache next to the reader: after reading, a platter stays in one of
    # cache_slots places (LRU) instead of being returned; a later request for it
    # is moved straight into the read-ahead buffer (handoff_s), with no shuttle.
    cache_slots: int = 0

    def validate(self):
        if self.rows != 8 or self.shuttles not in (1, 2, 4, 8):
            raise ValueError("Eight rack rows; Zone needs 1/2/4/8 shuttles")
        for name in ("slots_per_row", "output_slots", "docking_bays"):
            if not isinstance(getattr(self, name), int) or getattr(self, name) < 1:
                raise ValueError(f"Invalid {name}")
        if not isinstance(self.cache_slots, int) or self.cache_slots < 0 or (self.cache_slots and not self.buffer_slots):
            raise ValueError("cache_slots must be >= 0 and needs a read-ahead buffer")
        if not isinstance(self.buffer_slots, int) or self.buffer_slots < 0:
            raise ValueError("Invalid buffer_slots")
        if self.docking_bays < self.shuttles:
            raise ValueError("Docking bays must cover the fleet")
        for name, value in asdict(self).items():
            if isinstance(value, float) and (not math.isfinite(value) or value < 0
                                             or (value == 0 and name not in ("yield_penalty_s", "contention_hold_s"))):
                raise ValueError(f"Invalid {name}")

    @property
    def platters(self):
        return self.rows * self.slots_per_row

    def home(self, platter):
        row, slot = divmod(platter, self.slots_per_row)
        return (row, (slot + .5) / self.slots_per_row * self.length_m)

    def owner(self, platter):
        return (platter // self.slots_per_row) * self.shuttles // self.rows

    def read_time(self, size_bytes):
        return self.request_overhead_s + size_bytes / (self.read_mb_s * 1e6)


@dataclass(frozen=True)
class Request:
    index: int
    arrival_s: float
    platter: int
    size_bytes: int


# Silica SOSP'23 §2: 58.7% of reads are <= 4 MiB; files > 256 MiB are < 2% of reads
# but ~85% of bytes. Log-uniform buckets reproduce those shares (large share of
# bytes ~85%); the bucket bounds themselves are assumptions.
SILICA_SIZE_MIX = ((0.587, 4 * 1024, 4 * MiB), (0.393, 4 * MiB, 256 * MiB), (0.020, 256 * MiB, 32 * GiB))


def draw_size(rng, mix=SILICA_SIZE_MIX):
    x, acc = rng.random(), 0.0
    for share, lo, hi in mix:
        acc += share
        if x < acc:
            return int(math.exp(rng.uniform(math.log(lo), math.log(hi))))
    _, lo, hi = mix[-1]
    return int(math.exp(rng.uniform(math.log(lo), math.log(hi))))


def make_burst(config, count, seed, platters=None, window_s=0.0, mix=SILICA_SIZE_MIX):
    """A restore-style burst: `count` file reads arriving within `window_s`.

    platters=None: every file is on an independent uniformly random platter.
    platters=k: files are spread over k distinct platters chosen uniformly at
    random across the library (Silica spreads a platter-set's members apart, §6).
    """
    if count < 1 or window_s < 0 or (platters is not None and not 1 <= platters <= config.platters):
        raise ValueError("Invalid burst workload")
    rng = random.Random(seed)
    pool = rng.sample(range(config.platters), platters) if platters else None
    arrivals = sorted(rng.uniform(0, window_s) if window_s else 0.0 for _ in range(count))
    return [Request(i, t, rng.choice(pool) if pool else rng.randrange(config.platters), draw_size(rng, mix))
            for i, t in enumerate(arrivals)]


# ---------------------------------------------------------------- schedulers
class Scheduler:
    """Decides which platter an idle shuttle fetches, and what the trip serves.

    pick_fetch(sim, sid) -> platter or None, choosing among sim.accessible(sid).
    merge: whether a trip serves every queued request for its platter, and
    whether requests arriving while the platter is away join it before reading ends.
    """
    name = "base"
    merge = True

    def pick_fetch(self, sim, sid):
        raise NotImplementedError

    def pick_read(self, sim):
        return 0  # index into sim.inbox; FIFO by arrival at the reader


class FIFO(Scheduler):
    """B0: oldest request first, one request per trip (no merging)."""
    name, merge = "B0_fifo", False

    def pick_fetch(self, sim, sid):
        best = min(sim.accessible(sid), key=lambda p: sim.queue[p][0], default=None)
        return best


class SilicaFIFO(Scheduler):
    """B1: platter holding the earliest queued request among accessible platters;
    all queued requests for that platter are served in one trip (SOSP'23 §4.1)."""
    name, merge = "B1_silica", True

    def pick_fetch(self, sim, sid):
        return min(sim.accessible(sid), key=lambda p: sim.queue[p][0], default=None)


SCHEDULERS = {s.name: s for s in (FIFO, SilicaFIFO)}


# ---------------------------------------------------------------- simulation
class IOSimulation:
    def __init__(self, config: IOConfig, requests: list[Request], scheduler: Scheduler, record=False):
        config.validate()
        if not requests or [r.index for r in requests] != list(range(len(requests))):
            raise ValueError("Requests need consecutive IDs")
        if any(a.arrival_s > b.arrival_s for a, b in zip(requests, requests[1:])):
            raise ValueError("Requests must be arrival sorted")
        if any(not 0 <= r.platter < config.platters or r.size_bytes < 0 for r in requests):
            raise ValueError("Invalid request values")
        self.c, self.requests, self.sched = config, requests, scheduler
        self.rail = Rail(config)
        self.clock = requests[0].arrival_s
        self.events, self.serial = [], 0
        self.shuttles = [dict(id=i, position=Rail.READER, idle=True) for i in range(config.shuttles)]
        self.queue: dict[int, list[int]] = {}   # platter -> queued request ids (platter at home)
        self.away: dict[int, int] = {}           # platter -> trip id while not at home
        self.trips: list[dict[str, Any]] = []
        self.waiting, self.inbox, self.output = [], [], []
        self.gate_busy = False
        self.reader_state, self.reader_trip = "idle", None
        self.done_s = [None] * len(requests)
        self.reader_busy_s = self.reader_starved_s = 0.0
        self.decisions, self.decision_cpu_s, self.decision_queue_sum = 0, 0.0, 0
        self.max_dock = 0
        self.unread = 0  # trips dispatched but not finished reading
        self.shuttle_idle_s = self.shuttle_restricted_idle_s = 0.0
        self.reader_req = None
        self.cache: OrderedDict[int, int] = OrderedDict()   # platter -> trip that read it, LRU first
        self.inbox_reserved = 0                              # buffer slots promised to cache moves
        self.cache_hits = self.evictions = 0
        # optional state trace: (time, reader_state, size of request being read, buffer, shuttles at gate, idle shuttles)
        self.trace = [] if record else None
        self.reader_state_s = dict(read=0.0, blocked=0.0, unload=0.0, idle_demand=0.0, idle_empty=0.0)
        for r in requests:
            self.push(r.arrival_s, "arrival", r.index)

    def push(self, when, kind, payload):
        if when < self.clock - 1e-7:
            raise RuntimeError("Event in past")
        self.serial += 1
        heapq.heappush(self.events, (when, self.serial, kind, payload))

    def accessible(self, sid):
        """Queued platters at home that shuttle sid may fetch (Zone ownership)."""
        return [p for p, q in self.queue.items() if q and p not in self.away and self.c.owner(p) == sid]

    def move(self, sid, tid, target, phase, event):
        shuttle, trip = self.shuttles[sid], self.trips[tid]
        start, end = self.rail.reserve(shuttle["position"], target, self.clock, sid, tid, phase)
        trip["move_s"] += end - start
        trip["traffic_wait_s"] += start - self.clock
        self.push(end, event, (sid, tid, target))

    # -- decisions
    def dispatch(self):
        changed = False
        for tid in list(self.output):
            trip = self.trips[tid]
            if trip["return_assigned"]:
                continue
            s = self.shuttles[self.c.owner(trip["platter"])]
            if s["idle"]:
                s["idle"], trip["return_assigned"] = False, True
                self.move(s["id"], tid, Rail.READER, "to_output", "at_output")
                changed = True
        for s in self.shuttles:
            if not s["idle"]:
                continue
            t0 = time.perf_counter()
            platter = self.sched.pick_fetch(self, s["id"])
            self.decision_cpu_s += time.perf_counter() - t0
            self.decisions += 1
            self.decision_queue_sum += sum(len(q) for q in self.queue.values())
            if platter is None:
                continue
            q = self.queue[platter]
            served = list(q) if self.sched.merge else [q[0]]
            del q[:len(served)]
            if not q:
                del self.queue[platter]
            tid = len(self.trips)
            self.trips.append(dict(trip=tid, platter=platter, shuttle=s["id"], requests=served,
                                   dispatch_s=self.clock, move_s=0.0, traffic_wait_s=0.0,
                                   gate_wait_s=0.0, return_assigned=False, read_done=False))
            self.away[platter] = tid
            self.unread += 1
            s["idle"] = False
            self.move(s["id"], tid, self.c.home(platter), "fetch", "at_platter")
            changed = True
        return changed

    def pump(self):
        changed = False
        cache_room = self.c.cache_slots and len(self.cache) < self.c.cache_slots
        if self.reader_state == "blocked" and (cache_room or len(self.output) < self.c.output_slots):
            self.reader_state = "unload"
            self.reader_busy_s += self.c.unload_s
            self.push(self.clock + self.c.unload_s, "unloaded", self.reader_trip)
            changed = True
        if self.reader_state == "idle" and self.inbox:
            tid = self.inbox.pop(self.sched.pick_read(self))
            self.reader_state, self.reader_trip = "read", tid
            trip = self.trips[tid]
            trip["read_start_s"], trip["served"] = self.clock, 0
            self.reader_busy_s += self.c.load_mount_s
            self.push(self.clock + self.c.load_mount_s, "read_next", tid)
            changed = True
        for platter in list(self.cache):
            if not self.queue.get(platter) or len(self.inbox) + self.inbox_reserved >= self.c.buffer_slots:
                continue
            served = self.queue.pop(platter)
            del self.cache[platter]
            tid = len(self.trips)
            self.trips.append(dict(trip=tid, platter=platter, shuttle=None, requests=served, from_cache=True,
                                   dispatch_s=self.clock, move_s=0.0, traffic_wait_s=0.0,
                                   gate_wait_s=0.0, return_assigned=False, read_done=False))
            self.away[platter] = tid
            self.unread += 1
            self.cache_hits += 1
            self.inbox_reserved += 1
            self.push(self.clock + self.c.handoff_s, "cache_to_inbox", tid)
            changed = True
        if not self.gate_busy and self.waiting:
            kind, sid, tid = self.waiting[0]
            room = (self.c.buffer_slots > 0 and len(self.inbox) + self.inbox_reserved < self.c.buffer_slots) or \
                   (self.c.buffer_slots == 0 and self.reader_state == "idle")
            if kind == "return" or room:
                self.waiting.pop(0)
                self.gate_busy = True
                trip = self.trips[tid]
                if kind == "deliver":
                    trip["gate_wait_s"] = self.clock - trip["at_reader_s"]
                    if self.c.buffer_slots:
                        self.inbox_reserved += 1   # the slot is promised while the handoff runs
                    self.push(self.clock + self.c.handoff_s, "handed_off", (sid, tid))
                else:
                    self.push(self.clock + self.c.pick_s, "return_picked", (sid, tid))
                changed = True
        self.max_dock = max(self.max_dock, len(self.waiting) + int(self.gate_busy))
        if len(self.inbox) + self.inbox_reserved > self.c.buffer_slots or len(self.cache) > self.c.cache_slots or len(self.output) > self.c.output_slots or self.max_dock > self.c.docking_bays:
            raise RuntimeError("Finite staging capacity exceeded")
        return changed

    def handle(self, kind, payload):
        if kind == "arrival":
            r = self.requests[payload]
            tid = self.away.get(r.platter)
            if self.sched.merge and tid is not None and not self.trips[tid]["read_done"]:
                self.trips[tid]["requests"].append(payload)   # joins the trip in flight
            else:
                self.queue.setdefault(r.platter, []).append(payload)
        elif kind in ("at_platter", "at_reader", "at_output", "at_home"):
            sid, tid, target = payload
            self.shuttles[sid]["position"] = target
            if kind == "at_platter":
                self.push(self.clock + self.c.pick_s, "picked", (sid, tid))
            elif kind == "at_reader":
                self.trips[tid]["at_reader_s"] = self.clock
                self.waiting.append(("deliver", sid, tid))
            elif kind == "at_output":
                i = next((i for i, v in enumerate(self.waiting) if v[0] == "deliver"), len(self.waiting))
                self.waiting.insert(i, ("return", sid, tid))   # returns first: avoids circular blocking
            else:
                self.push(self.clock + self.c.place_s, "returned", (sid, tid))
        elif kind == "picked":
            sid, tid = payload
            self.move(sid, tid, Rail.READER, "delivery", "at_reader")
        elif kind == "handed_off":
            sid, tid = payload
            self.gate_busy = False
            self.shuttles[sid]["idle"] = True
            if self.c.buffer_slots:
                self.inbox_reserved -= 1
                self.inbox.append(tid)
            else:
                self.inbox.insert(0, tid)
        elif kind == "read_next":
            trip = self.trips[payload]
            if trip["served"]:
                self.done_s[trip["requests"][trip["served"] - 1]] = self.clock
            if trip["served"] < len(trip["requests"]):
                rid = trip["requests"][trip["served"]]
                self.reader_req = rid
                trip["served"] += 1
                d = self.c.read_time(self.requests[rid].size_bytes)
                self.reader_busy_s += d
                self.push(self.clock + d, "read_next", payload)
            else:
                trip["read_done"], trip["read_done_s"] = True, self.clock
                self.reader_req = None
                self.unread -= 1
                self.reader_state = "blocked"
        elif kind == "unloaded":
            self.reader_state, self.reader_trip = "idle", None
            if self.c.cache_slots:
                self.cache[self.trips[payload]["platter"]] = payload
                if len(self.cache) > self.c.cache_slots:
                    _, victim = self.cache.popitem(last=False)   # least recently used goes home
                    self.output.append(victim)
                    self.evictions += 1
            else:
                self.output.append(payload)
        elif kind == "cache_to_inbox":
            self.inbox_reserved -= 1
            self.inbox.append(payload)
        elif kind == "return_picked":
            sid, tid = payload
            self.gate_busy = False
            self.output.remove(tid)
            self.move(sid, tid, self.c.home(self.trips[tid]["platter"]), "return", "at_home")
        elif kind == "returned":
            sid, tid = payload
            trip = self.trips[tid]
            trip["returned_s"] = self.clock
            del self.away[trip["platter"]]
            self.shuttles[sid]["idle"] = True
        else:
            raise RuntimeError(f"Unknown event {kind}")

    def run(self):
        steps = 0
        while self.events:
            at = self.events[0][0]
            dt = at - self.clock
            if self.reader_state == "idle":
                demand = bool(self.queue or self.unread)
                self.reader_starved_s += dt * demand
                self.reader_state_s["idle_demand" if demand else "idle_empty"] += dt
            else:
                self.reader_state_s[self.reader_state] += dt
            idle = [x["id"] for x in self.shuttles if x["idle"]]
            self.shuttle_idle_s += dt * len(idle)
            if idle and self.queue:
                # idle while queued work exists only outside its own zone (pooling loss)
                owners = {self.c.owner(p) for p in self.queue if p not in self.away}
                self.shuttle_restricted_idle_s += dt * sum(1 for i in idle if i not in owners and owners)
            self.clock = at
            while self.events and self.events[0][0] <= at + 1e-10:
                _, _, kind, payload = heapq.heappop(self.events)
                self.handle(kind, payload)
            while self.pump() | self.dispatch():
                pass
            if self.trace is not None:
                state = self.reader_state
                if state == "read" and self.reader_req is None:
                    state = "mount"
                if state == "idle":
                    state = "starved" if (self.queue or self.unread) else "empty"
                size = self.requests[self.reader_req].size_bytes if state == "read" else 0
                self.trace.append((self.clock, state, size, len(self.inbox),
                                   sum(1 for w in self.waiting if w[0] == "deliver"),
                                   sum(1 for x in self.shuttles if x["idle"])))
            steps += 1
            if steps > 200 * len(self.requests) + 1000:
                raise RuntimeError("No progress")
        if None in self.done_s or self.queue or set(self.away) - set(self.cache) or self.inbox or self.output or self.waiting:
            raise RuntimeError("Incomplete or deadlocked run")
        self.rail.validate()
        return self.summary()

    def summary(self):
        t0 = self.requests[0].arrival_s
        lats = [d - r.arrival_s for d, r in zip(self.done_s, self.requests)]
        makespan = max(self.done_s) - t0
        trips = self.trips
        lb = lower_bound(self.c, self.requests, merge=self.sched.merge)
        return dict(
            scheduler=self.sched.name, requests=len(self.requests), trips=len(trips),
            cache_hits=self.cache_hits, fetch_trips=len(trips) - self.cache_hits, evictions=self.evictions,
            requests_per_trip=len(self.requests) / len(trips),
            makespan_s=makespan, mean_s=mean(lats), p99_s=quantile(lats, .99),
            lower_bound_s=lb["bound_s"], lb_binding=lb["binding"], gap_vs_lb=makespan / lb["bound_s"] - 1,
            reader_busy_fraction=self.reader_busy_s / (self.clock - t0),
            reader_starved_s=self.reader_starved_s,
            reader_starved_fraction=self.reader_starved_s / makespan,
            move_s=sum(t["move_s"] for t in trips), traffic_wait_s=sum(t["traffic_wait_s"] for t in trips),
            gate_wait_s=sum(t["gate_wait_s"] for t in trips),
            decisions=self.decisions, decision_cpu_us=1e6 * self.decision_cpu_s / max(1, self.decisions),
            mean_queue_at_decision=self.decision_queue_sum / max(1, self.decisions),
            max_dock=self.max_dock,
            shuttle_idle_s=self.shuttle_idle_s, shuttle_restricted_idle_s=self.shuttle_restricted_idle_s,
            shuttle_time_s=self.c.shuttles * (self.clock - t0),
            empty_move_s=sum(r["end_s"] - r["start_s"] for r in self.rail.records if r["phase"] in ("fetch", "to_output")),
            loaded_move_s=sum(r["end_s"] - r["start_s"] for r in self.rail.records if r["phase"] in ("delivery", "return")),
            pooled_transport_lb_s=lb["pooled_transport_s"],
            **{f"reader_{k}_s": v for k, v in self.reader_state_s.items()},
            workload_sha256=hashlib.sha256(json.dumps([asdict(r) for r in self.requests]).encode()).hexdigest())


def lower_bound(config, requests, merge=True):
    """Makespan lower bound valid for every scheduler with the given merge rule.

    reader: every distinct visit must be mounted, read and unloaded on one reader
            (merge: one visit per distinct platter; no merge: one per request).
    zone:   each shuttle must carry each of its visits to the reader and back:
            2 x one-way free-flow travel + pick + handoff + output pick + place.
    path:   any single request needs fetch + delivery + mount + its read after arrival.
    Empty repositioning, congestion and gate queuing are ignored, so the bound is loose.
    """
    rail, c = Rail(config), config
    one_way = {}
    def oneway(p):
        if p not in one_way:
            one_way[p] = sum(d for _, d in rail.path(Rail.READER, c.home(p)))
        return one_way[p]
    t0 = requests[0].arrival_s
    reads = sum(c.read_time(r.size_bytes) for r in requests)
    visits = sorted({r.platter for r in requests}) if merge else [r.platter for r in requests]
    reader = sum(c.load_mount_s + c.unload_s for _ in visits) + reads
    per_shuttle = [0.0] * c.shuttles
    for p in visits:
        per_shuttle[c.owner(p)] += 2 * oneway(p) + c.pick_s + c.handoff_s + c.pick_s + c.place_s
    path = max(r.arrival_s - t0 + 2 * oneway(r.platter) + c.pick_s + c.handoff_s + c.load_mount_s
               + c.read_time(r.size_bytes) for r in requests)
    pooled = sum(per_shuttle) / c.shuttles
    bounds = dict(reader=reader, zone=max(per_shuttle), path=path)
    binding = max(bounds, key=bounds.get)
    return dict(bound_s=bounds[binding], binding=binding, pooled_transport_s=pooled, **bounds)
