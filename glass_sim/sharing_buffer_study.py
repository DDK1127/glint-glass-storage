"""Controlled eight-zone sharing study; an explicit service/transport abstraction.

Not a Silica digital twin. Whole-route exclusive reservations avoid on-rail
waiting. Each zone has eight off-rail shuttle bays (fixed in every experiment).
Readers have finite input staging and exactly one output slot. No prefetch,
cache, request merging, teleportation, or idealized collision-free policy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import heapq
import math
import random
from statistics import mean
from typing import Any


@dataclass(frozen=True)
class Model:
    zones: int = 8
    slots_per_zone: int = 80
    lane_length_m: float = 16.0
    zone_pitch_m: float = 1.0
    horizontal_speed_m_s: float = 2.0
    horizontal_acceleration_m_s2: float = 2.0
    trunk_speed_m_s: float = 1.0 / 3.0
    alignment_s: float = 0.5
    pick_s: float = 1.0
    place_s: float = 1.0
    handoff_s: float = 1.0
    load_s: float = 1.0
    mount_s: float = 1.0
    read_mib: float = 480.0
    reader_mib_s: float = 60.0
    unload_s: float = 1.0

    def validate(self) -> None:
        if self.zones != 8 or not isinstance(self.slots_per_zone, int) or self.slots_per_zone < 1:
            raise ValueError("Use eight zones and a positive integer slot count")
        for key, value in asdict(self).items():
            if key not in {"zones", "slots_per_zone"} and (not math.isfinite(value) or value <= 0):
                raise ValueError(f"{key} must be positive and finite")

    @property
    def read_service_s(self) -> float:
        return self.load_s + self.mount_s + self.read_mib / self.reader_mib_s

    def position(self, platter: int) -> tuple[int, float]:
        zone, slot = divmod(platter, self.slots_per_zone)
        return zone, (slot + 0.5) * self.lane_length_m / self.slots_per_zone


@dataclass(frozen=True)
class Request:
    index: int
    arrival_s: float
    platter: int


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lo = int(index)
    return ordered[lo] + (ordered[min(lo + 1, len(ordered) - 1)] - ordered[lo]) * (index - lo)


def horizontal_time(distance: float, model: Model) -> float:
    if distance < 1e-12:
        return 0.0
    speed, accel = model.horizontal_speed_m_s, model.horizontal_acceleration_m_s2
    threshold = speed * speed / accel
    return (2 * math.sqrt(distance / accel) if distance <= threshold
            else 2 * speed / accel + (distance - threshold) / speed)


class Transport:
    """Eight exclusive local lanes and one exclusive connecting trunk.

    All needed resources are reserved for the entire route, conservatively.
    Waiting happens before departure at a dock, never on a reserved lane.
    """

    def __init__(self, model: Model):
        self.model = model
        self.free: dict[str, float] = {}
        self.records: list[dict[str, Any]] = []

    def estimate(self, source, target, now: float):
        zs, xs = source
        zt, xt = target
        resources = []
        if zs == zt:
            duration = horizontal_time(abs(xt - xs), self.model)
            if duration:
                resources.append(f"lane_{zs}")
        else:
            duration = (horizontal_time(xs, self.model) + horizontal_time(xt, self.model)
                        + abs(zt - zs) * self.model.zone_pitch_m / self.model.trunk_speed_m_s)
            resources.append("trunk")
            if xs > 0:
                resources.append(f"lane_{zs}")
            if xt > 0:
                resources.append(f"lane_{zt}")
        if duration:
            duration += self.model.alignment_s
        start = max([now] + [self.free.get(resource, 0.0) for resource in resources])
        return start, start + duration, resources

    def reserve(self, source, target, now, shuttle, request, phase):
        start, end, resources = self.estimate(source, target, now)
        for resource in resources:
            self.free[resource] = end
            self.records.append(dict(resource=resource, start_s=start, end_s=end,
                                     shuttle=shuttle, request=request, phase=phase))
        return start, end

    def validate(self):
        for resource in self.free:
            records = sorted((r for r in self.records if r["resource"] == resource), key=lambda r: r["start_s"])
            if any(b["start_s"] < a["end_s"] - 1e-8 for a, b in zip(records, records[1:])):
                raise RuntimeError(f"Overlapping transport reservations: {resource}")


def workload(model: Model, count: int, seed: int, rate: float, pattern: str) -> list[Request]:
    """Paired timestamps and local slots; only zone demand changes by pattern.

    Middle third: hotspot puts 65% of requests into central zones 3 and 4.
    Fixed-size independent reads, one fetch/read/return per request; no merging.
    """
    if count < 8 or rate <= 0 or pattern not in {"uniform", "hotspot"}:
        raise ValueError("Invalid workload parameters")
    timing, placement = random.Random(seed), random.Random(seed + 1000003)
    now = 0.0
    rows = []
    for i in range(count):
        now += timing.expovariate(rate)
        zone_draw, slot = placement.random(), placement.randrange(model.slots_per_zone)
        if pattern == "hotspot" and count // 3 <= i < 2 * count // 3:
            if zone_draw < 0.65:
                zone = 3 + int(zone_draw / 0.65 * 2)
            else:
                zone = [0, 1, 2, 5, 6, 7][min(5, int((zone_draw - 0.65) / 0.35 * 6))]
        else:
            zone = min(7, int(zone_draw * 8))
        rows.append(Request(i, now, zone * model.slots_per_zone + slot))
    return rows


class Simulator:
    def __init__(self, model: Model, requests: list[Request], mode: str, group_size: int, buffer_slots: int):
        model.validate()
        if mode not in {"fixed", "transport", "joint"}:
            raise ValueError("Unknown sharing mode")
        if group_size not in {1, 2, 4, 8} or (mode == "fixed" and group_size != 1):
            raise ValueError("Invalid contiguous sharing group")
        if not isinstance(buffer_slots, int) or buffer_slots < 0:
            raise ValueError("buffer_slots must be a nonnegative integer")
        if not requests or [r.index for r in requests] != list(range(len(requests))):
            raise ValueError("Requests must have consecutive indices")
        if any(not math.isfinite(r.arrival_s) or r.arrival_s < 0 or not 0 <= r.platter < 8 * model.slots_per_zone for r in requests):
            raise ValueError("Invalid request")
        if any(b.arrival_s < a.arrival_s for a, b in zip(requests, requests[1:])):
            raise ValueError("Requests must be sorted by arrival")
        self.model, self.requests = model, requests
        self.mode, self.group_size, self.capacity = mode, group_size, buffer_slots
        self.clock = requests[0].arrival_s
        self.transport = Transport(model)
        self.shuttles = [dict(id=i, position=(i, 0.0), idle=True, transit=False) for i in range(8)]
        self.readers = [dict(state="idle", job=None, end=self.clock, inbox=[], waiting=[], output=None) for _ in range(8)]
        self.events: list[tuple[float, int, str, Any]] = []
        self.serial = 0
        self.pending: list[int] = []
        self.away: set[int] = set()
        self.jobs: dict[int, dict[str, Any]] = {}
        self.timeline: list[dict[str, Any]] = []
        self.returned = 0
        self.integrals = dict(excluded_ready_work_idle_shuttle_s=0.0,
                              idle_reader_with_demand_s=0.0, input_slot_occupancy_s=0.0)
        self.max_input_depth = 0
        self.max_docked_shuttles = 0
        for request in requests:
            self.push(request.arrival_s, "arrival", request.index)

    def push(self, when, kind, payload):
        if when < self.clock - 1e-8:
            raise RuntimeError("Event scheduled in the past")
        self.serial += 1
        heapq.heappush(self.events, (when, self.serial, kind, payload))

    def log(self, resource, phase, start, end, request):
        if end > start + 1e-10:
            self.timeline.append(dict(resource=resource, phase=phase, start_s=start, end_s=end, request=request))

    def allowed(self, shuttle_id: int, home_zone: int) -> bool:
        return shuttle_id // self.group_size == home_zone // self.group_size

    def reader_candidates(self, home_zone):
        if self.mode != "joint":
            return [home_zone]
        first = home_zone // self.group_size * self.group_size
        return list(range(first, first + self.group_size))

    def move(self, sid, jid, target, phase, next_event):
        shuttle = self.shuttles[sid]
        start, end = self.transport.reserve(shuttle["position"], target, self.clock, sid, jid, phase)
        job = self.jobs[jid]
        job["movement_s"] += end - start
        job["traffic_wait_s"] += start - self.clock
        self.log(f"shuttle_{sid}", "traffic_wait", self.clock, start, jid)
        self.log(f"shuttle_{sid}", phase, start, end, jid)
        self.push(start, "depart", sid)
        self.push(end, next_event, (sid, jid, target))

    def reader_score(self, rid, arrival):
        reader = self.readers[rid]
        # Includes every assigned but unread job, including in-flight deliveries.
        committed = sum(j["reader"] == rid and j["read_done_s"] is None for j in self.jobs.values())
        if reader["state"] == "read":
            committed -= 1
        release = max(self.clock, reader["end"])
        if reader["state"] == "read":
            release += self.model.unload_s
        if reader["state"] == "blocked":
            # One extra cycle is a documented heuristic for uncertain return release.
            release += self.model.read_service_s + self.model.unload_s
        cycle = self.model.read_service_s + self.model.unload_s
        return max(arrival, release + max(0, committed) * cycle) + self.model.read_service_s

    def dispatch(self):
        changed = False
        # Return priority prevents finite output staging from being ignored.
        for rid, reader in sorted(enumerate(self.readers), key=lambda p: (p[1]["output"] is None, p[0])):
            jid = reader["output"]
            if jid is None or self.jobs[jid]["return_assigned"]:
                continue
            job = self.jobs[jid]
            eligible = [s for s in self.shuttles if s["idle"] and self.allowed(s["id"], job["home"])]
            if not eligible:
                continue
            shuttle = min(eligible, key=lambda s: (self.transport.estimate(s["position"], (rid, 0.0), self.clock)[1], s["id"]))
            shuttle["idle"] = False
            job["return_assigned"] = True
            self.move(shuttle["id"], jid, (rid, 0.0), "to_output", "at_output")
            changed = True
        for jid in list(self.pending):
            request = self.requests[jid]
            if request.platter in self.away:
                continue
            home = request.platter // self.model.slots_per_zone
            eligible = [s for s in self.shuttles if s["idle"] and self.allowed(s["id"], home)]
            if not eligible:
                continue
            target = self.model.position(request.platter)
            shuttle = min(eligible, key=lambda s: (self.transport.estimate(s["position"], target, self.clock)[1], s["id"]))
            sid = shuttle["id"]
            picked = self.transport.estimate(shuttle["position"], target, self.clock)[1] + self.model.pick_s
            rid = min(self.reader_candidates(home), key=lambda r: (self.reader_score(r, self.transport.estimate(target, (r, 0.0), picked)[1] + self.model.handoff_s), r))
            self.jobs[jid] = dict(request=jid, platter=request.platter, home=home, reader=rid,
                                  shuttle=sid, arrival_s=request.arrival_s, dispatch_s=self.clock,
                                  movement_s=0.0, traffic_wait_s=0.0, delivery_wait_s=0.0,
                                  output_block_s=0.0, read_done_s=None, returned_s=None,
                                  return_assigned=False, stage_ready=False)
            shuttle["idle"] = False
            self.pending.remove(jid)
            self.away.add(request.platter)
            self.move(sid, jid, target, "fetch", "at_platter")
            changed = True
        return changed

    def pump_readers(self):
        changed = False
        for rid, reader in enumerate(self.readers):
            if reader["state"] == "blocked" and reader["output"] is None:
                jid = reader["job"]
                job = self.jobs[jid]
                job["output_block_s"] = self.clock - job["read_done_s"]
                self.log(f"reader_{rid}", "output_block", job["read_done_s"], self.clock, jid)
                reader["state"] = "unload"
                reader["end"] = self.clock + self.model.unload_s
                self.log(f"reader_{rid}", "unload", self.clock, reader["end"], jid)
                self.push(reader["end"], "unloaded", (rid, jid))
                changed = True
            while reader["waiting"]:
                if self.capacity == 0:
                    can_admit = reader["state"] == "idle"
                else:
                    can_admit = len(reader["inbox"]) < self.capacity
                if not can_admit:
                    break
                sid, jid = reader["waiting"].pop(0)
                job = self.jobs[jid]
                job["delivery_wait_s"] = self.clock - job["at_reader_s"]
                self.log(f"shuttle_{sid}", "delivery_wait", job["at_reader_s"], self.clock, jid)
                self.log(f"shuttle_{sid}", "handoff", self.clock, self.clock + self.model.handoff_s, jid)
                job["admitted_s"] = self.clock
                if self.capacity == 0:
                    reader["state"], reader["job"] = "handoff", jid
                    reader["end"] = self.clock + self.model.handoff_s
                else:
                    reader["inbox"].append(jid)
                self.push(self.clock + self.model.handoff_s, "handed_off", (sid, jid, rid))
                changed = True
            if reader["state"] == "idle" and reader["inbox"]:
                jid = reader["inbox"][0]
                if self.jobs[jid]["stage_ready"]:
                    reader["inbox"].pop(0)
                    self.start_read(rid, jid)
                    changed = True
            self.max_input_depth = max(self.max_input_depth, len(reader["inbox"]))
            if len(reader["inbox"]) > self.capacity:
                raise RuntimeError("Input staging overflow")
        return changed

    def start_read(self, rid, jid):
        reader, job = self.readers[rid], self.jobs[jid]
        reader["state"], reader["job"] = "read", jid
        reader["end"] = self.clock + self.model.read_service_s
        job["read_start_s"] = self.clock
        self.log(f"reader_{rid}", "load_mount_read", self.clock, reader["end"], jid)
        self.push(reader["end"], "read_done", (rid, jid))

    def handle(self, kind, payload):
        if kind == "arrival":
            self.pending.append(payload)
        elif kind == "depart":
            self.shuttles[payload]["transit"] = True
        elif kind in {"at_platter", "at_reader", "at_output", "at_home"}:
            sid, jid, target = payload
            shuttle = self.shuttles[sid]
            shuttle["position"], shuttle["transit"] = target, False
            if kind == "at_platter":
                self.log(f"shuttle_{sid}", "pick", self.clock, self.clock + self.model.pick_s, jid)
                self.push(self.clock + self.model.pick_s, "picked", (sid, jid))
            elif kind == "at_reader":
                self.jobs[jid]["at_reader_s"] = self.clock
                self.readers[self.jobs[jid]["reader"]]["waiting"].append((sid, jid))
            elif kind == "at_output":
                self.log(f"shuttle_{sid}", "output_pick", self.clock, self.clock + self.model.pick_s, jid)
                self.push(self.clock + self.model.pick_s, "return_picked", (sid, jid))
            else:
                self.log(f"shuttle_{sid}", "place", self.clock, self.clock + self.model.place_s, jid)
                self.push(self.clock + self.model.place_s, "returned", (sid, jid))
        elif kind == "picked":
            sid, jid = payload
            self.move(sid, jid, (self.jobs[jid]["reader"], 0.0), "delivery", "at_reader")
        elif kind == "handed_off":
            sid, jid, rid = payload
            self.shuttles[sid]["idle"] = True
            self.jobs[jid]["stage_ready"] = True
            self.jobs[jid]["handoff_done_s"] = self.clock
            if self.capacity == 0:
                self.start_read(rid, jid)
        elif kind == "read_done":
            rid, jid = payload
            if self.jobs[jid]["read_done_s"] is not None:
                raise RuntimeError("Duplicate read")
            self.jobs[jid]["read_done_s"] = self.clock
            self.readers[rid]["state"] = "blocked"
        elif kind == "unloaded":
            rid, jid = payload
            reader = self.readers[rid]
            if reader["output"] is not None:
                raise RuntimeError("Output staging overflow")
            reader["output"], reader["state"], reader["job"] = jid, "idle", None
        elif kind == "return_picked":
            sid, jid = payload
            rid = self.jobs[jid]["reader"]
            if self.readers[rid]["output"] != jid:
                raise RuntimeError("Wrong platter at output")
            self.readers[rid]["output"] = None
            self.move(sid, jid, self.model.position(self.jobs[jid]["platter"]), "return", "at_home")
        elif kind == "returned":
            sid, jid = payload
            self.shuttles[sid]["idle"] = True
            self.away.remove(self.jobs[jid]["platter"])
            self.jobs[jid]["returned_s"] = self.clock
            self.returned += 1
        else:
            raise RuntimeError(f"Unknown event {kind}")

    def integrate(self, dt):
        ready_homes = {self.requests[i].platter // self.model.slots_per_zone for i in self.pending if self.requests[i].platter not in self.away}
        for shuttle in self.shuttles:
            if shuttle["idle"] and ready_homes and not any(self.allowed(shuttle["id"], h) for h in ready_homes):
                self.integrals["excluded_ready_work_idle_shuttle_s"] += dt
        outstanding = {self.requests[i].platter // self.model.slots_per_zone for i in self.pending}
        outstanding.update(j["home"] for j in self.jobs.values() if j["read_done_s"] is None)
        for rid, reader in enumerate(self.readers):
            if reader["state"] == "idle" and any(rid in self.reader_candidates(h) for h in outstanding):
                self.integrals["idle_reader_with_demand_s"] += dt
            self.integrals["input_slot_occupancy_s"] += len(reader["inbox"]) * dt

    def run(self):
        iterations = 0
        while self.events:
            next_time = self.events[0][0]
            self.integrate(next_time - self.clock)
            self.clock = next_time
            while self.events and self.events[0][0] <= self.clock + 1e-10:
                _, _, kind, payload = heapq.heappop(self.events)
                self.handle(kind, payload)
            while True:
                changed = self.pump_readers()
                changed = self.dispatch() or changed
                if not changed:
                    break
            for zone in range(8):
                parked = sum(not s["transit"] and s["position"][0] == zone for s in self.shuttles)
                self.max_docked_shuttles = max(self.max_docked_shuttles, parked)
                if parked > 8:
                    raise RuntimeError("Finite shuttle bay capacity exceeded")
            iterations += 1
            if iterations > 100 * len(self.requests):
                raise RuntimeError("No progress")
        if self.returned != len(self.requests) or self.pending or self.away:
            raise RuntimeError(f"Deadlock or incomplete service: {self.returned}/{len(self.requests)} returned")
        self.transport.validate()
        self.validate_timeline()
        jobs = [self.jobs[i] for i in range(len(self.requests))]
        lats = [j["read_done_s"] - j["arrival_s"] for j in jobs]
        for j in jobs:
            phases = [j["arrival_s"], j["dispatch_s"], j["at_reader_s"], j["admitted_s"], j["handoff_done_s"], j["read_start_s"], j["read_done_s"], j["returned_s"]]
            if any(b < a - 1e-8 for a, b in zip(phases, phases[1:])):
                raise RuntimeError("Causality violation")
        summary = dict(mode=self.mode, group_size=self.group_size, buffer_slots=self.capacity,
                       requests=len(jobs), returned=self.returned, latency_mean_s=mean(lats),
                       latency_p99_s=percentile(lats, .99), read_completion_span_s=max(j["read_done_s"] for j in jobs) - self.requests[0].arrival_s,
                       system_span_s=self.clock - self.requests[0].arrival_s,
                       movement_s=sum(j["movement_s"] for j in jobs), traffic_wait_s=sum(j["traffic_wait_s"] for j in jobs),
                       delivery_wait_s=sum(j["delivery_wait_s"] for j in jobs), output_block_s=sum(j["output_block_s"] for j in jobs),
                       cross_zone_fetch_fraction=mean(j["shuttle"] != j["home"] for j in jobs),
                       cross_zone_reader_fraction=mean(j["reader"] != j["home"] for j in jobs),
                       max_input_depth=self.max_input_depth, max_docked_shuttles=self.max_docked_shuttles,
                       **self.integrals)
        summary["observed_read_throughput_req_s"] = len(jobs) / summary["read_completion_span_s"]
        components = {
            "dispatch_queue_mean_s": ("dispatch_s", "arrival_s"),
            "fetch_delivery_mean_s": ("at_reader_s", "dispatch_s"),
            "delivery_wait_mean_s": ("admitted_s", "at_reader_s"),
            "handoff_mean_s": ("handoff_done_s", "admitted_s"),
            "input_wait_mean_s": ("read_start_s", "handoff_done_s"),
            "reader_service_mean_s": ("read_done_s", "read_start_s"),
        }
        for name, (end, start) in components.items():
            summary[name] = mean(j[end] - j[start] for j in jobs)
        if not math.isclose(sum(summary[name] for name in components), summary["latency_mean_s"], abs_tol=1e-7):
            raise RuntimeError("Request latency accounting mismatch")
        summary["trace_sha256"] = hashlib.sha256(str([asdict(r) for r in self.requests]).encode()).hexdigest()
        return summary, jobs, self.timeline

    def validate_timeline(self):
        for resource in {row["resource"] for row in self.timeline}:
            rows = sorted((r for r in self.timeline if r["resource"] == resource), key=lambda r: r["start_s"])
            if any(b["start_s"] < a["end_s"] - 1e-8 for a, b in zip(rows, rows[1:])):
                raise RuntimeError(f"Overlapping service on {resource}")
