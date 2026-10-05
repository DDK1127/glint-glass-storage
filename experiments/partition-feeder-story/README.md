# Single-partition motivation study / 2026-09-30

## Registered plan (written before the full sweep)

The unit of study is ONE physical partition, ONE reader and 1/2/4/8 shuttles.
Zone means an internal contiguous rack-row ownership rule, not a separate
partition or reader. All shuttles converge on the same reader handoff station.
Earlier `sharing-buffer` outputs are not used as evidence for this architecture.

| Experiment | Fixed controls | Varied factors | Evidence question |
| --- | --- | --- | --- |
| E1 Provision | Zone scheduling, B=4, uniform saturated batch | Shuttle count, 16/64 m rack lanes, 2/8/24 s optical read | When does parallel supply raise reader utilization, and when does it saturate? |
| E2 Coordination | One reader, 32 m lanes, read=8 s, B=4 | Zone / Non-Zone FIFO / Non-Zone lookahead, 2/4/8 shuttles, uniform/hotspot | Sharing vs locality/traffic cost, at the same hardware count |
| E3 Buffer | One reader, 32 m lanes, uniform batch | Zone/FIFO, 4/8 shuttles, B=0/1/2/4, 2/8/24 s read | Does finite staging reduce blocked-shuttle time and improve completion? |
| E4 Arrival check | N=4, 32 m, read=8 s, paired Poisson arrivals | Zone/FIFO, B=0/4, uniform/hotspot | Do main mechanisms survive outside an all-at-once batch? |

Full sweep: 5 seeds × 384 requests per run. Expected workstation runtime:
minutes, no external compute or paid service. All cells are retained; unfavorable
results are not removed. Small smoke sweep precedes the full run. No promised
effect size. "Full" means the complete declared matrix, not paper-ready evidence.

## Explicit hardware and service assumptions

Eight fixed rack rows, each with 80 addressable platter slots. One reader is
connected at row 3. A horizontal lane is an exclusive block. Adjacent row
junctions have seven individually reserved connector blocks; they are NOT a
single global exclusive trunk. The reader approach is another exclusive block.
Different connector blocks can operate concurrently. Blocks are reserved only
during their traversal; wait occurs at endpoint docks before departure.

This is a conservative discrete resource model. It does not certify continuous
robot-body clearance or realistic junction microgeometry. Both Zone and
Non-Zone use identical capacities, paths and conflict checking, including shared
reader access. Zone is never declared globally collision-free.

Eight aggregate off-rail docking positions are provisioned at each rack endpoint
region, and eight reader-side shuttle waiting positions are fixed for ALL N/B.
These bays hold the shuttle and its carried platter, not a released feeder
platter. Bay access geometry is abstracted. A single handoff station serializes
delivery/output pickup. B=0: a delivering shuttle waits until reader is idle.
B>0: it waits until an input slot is available, then hands off and is released.
Input handoff can overlap reading. The same mechanism and handoff time exist
for every buffer capacity. Input is FIFO; no speculative prefetch or caching.

Return is fixed, not optimized: eight finite output slots, output tasks before
new fetches, output pickup before delivery at the common handoff station. Every
platter is physically returned to its original slot before reuse; the movement,
pick/place and waiting costs are included. A full output blocks unloading.
This choice avoids intentionally making a tiny output buffer the central study.

Requests are independent fixed-duration services with no merge; all modes perform
identical numbers of fetch/read/return cycles. A fixed read duration is a workload
parameter, not a hardware speed change. Repeated platter requests wait for return.
Batch tasks are all available at time zero; online decisions see only arrived work.
No steady-state p99 claim is made for these finite request episodes.

## Policies

- Zone: each shuttle owns 8/N contiguous rack rows, oldest feasible request.
- Non-Zone FIFO: oldest feasible request anywhere, idle shuttle with estimated
  earliest delivery (route reservations included).
- Non-Zone lookahead: considers up to 16 oldest feasible requests and chooses
  estimated earliest delivery; oldest request overrides this once waiting ≥120 s.
  This is a simple comparison heuristic, not a claimed novel or optimal method.
- Return policy, paths, physical capacities and conflict engine are identical.

Controller work is measured as assignment-pair evaluations and reservation
comparisons, plus CPU wall time. These are simulator workload indicators, not
measured embedded-controller latency or hardware area.

## Workload / statistics / provenance

Uniform maps requests over eight rows. Hotspot puts 75% of addresses in rows 0/1.
The hotspot is deliberately controlled, not an empirical Azure property. E4's
Poisson rate is 0.6 / (load+read+unload), identical for every compared method.
This is relative to the standalone reader ceiling, not actual system capacity.

Seeds change locations and (for E4) interarrivals; workload hashes verify pairing.
Each mean and sample SD is over independent seeded synthetic episodes; p99 is the
mean of per-run p99, not a pooled quantile. Error bars are SD, not confidence
intervals. Source/config hashes, effective configs and per-run data are retained.

Mechanics are illustrative: speed 2 m/s, acceleration 2 m/s², connector step 3 s,
alignment 0.5 s, pick/place/handoff/unload 1 s, load+mount 2 s. Silica §7.1 reports
about 0.5 s alignment and approximately 3 s crabbing; other values here are
controlled assumptions, not newly measured or wholly calibrated parameters.

Reference: https://www.microsoft.com/en-us/research/wp-content/uploads/2023/09/ProjectSilica-SOSP23.pdf

## Commands

```bash
.venv/bin/python -m unittest discover -s tests -p test_partition_feeder_study.py -v
.venv/bin/python scripts/run_partition_feeder_study.py --config experiments/partition-feeder-story/smoke.json
.venv/bin/python scripts/run_partition_feeder_study.py --config experiments/partition-feeder-story/full.json
.venv/bin/python scripts/run_shuttle_provisioning.py  # shuttle-count sweep N=1..32 (slides 3-4)
.venv/bin/python scripts/run_shuttle_congestion.py    # same sweep + stop-and-go congestion sensitivity
node scripts/build_partition_feeder_story.js
```

Primary metrics: read completion throughput, reader load/read/unload utilization,
mean/p99 request latency. Explanations: rail wait, actual movement, handoff wait,
reader idle with demand, buffer occupancy and output blockage. Return cost is
charged to resources and subsequent requests but not the current request's
completion. Resource seconds across parallel devices cannot be added as latency.

Prefetch-specific metrics in `runs.csv` separate the effect of B from movement:
`prefetch_hit_fraction` is the fraction of jobs handed off before that job's
reader start; `prefetch_lead_mean_s` is the mean positive early placement among
those hits; `route_motion_s` sums occupied fetch/delivery/return route time and
excludes the separate traffic-wait metric. A buffer should change the first two
without being claimed to shorten the physical route itself.

## Shuttle-count and congestion follow-up (2026-10-01)

`shuttle-provisioning.json` fixes 32 m, read=8 s, B=4, Non-Zone FIFO, uniform
batch and varies only N = 1..32 (docking bays fixed at 32 for every N). The
ideal line scales the N=1 reader utilization linearly; it is a lower bound on
the shuttles needed, not a recommended fleet size.

`shuttle-congestion.json` repeats the sweep for two scenarios: no congestion
(`contention_hold_s` = 0) and with congestion (0.9 s). The 0.9 s value was
SELECTED so that the congested throughput peak falls at N=8 for presentation;
it is an illustrative scenario, not a calibrated or derived value (during
exploration 0.5 s peaked at N=12, 0.8 s at N=9, 1.0 s at N=7). Each earlier reservation that blocks a route step adds one
stop-and-go of that length, and the extra time OCCUPIES the contested block,
so shared-block capacity falls as density rises. This is a deliberately simple
assumption chosen to expose a density-dependent capacity drop; the per-vehicle
scaling makes it strong, and the size of the decline depends on the chosen
value. It does not model physical spillback, parking geometry or deadlock.
Hold=0 reproduces the free-flow sweep exactly. A per-step (non-scaling) variant
tried during development lowered the curve but produced no decline in N.
