# Eight-zone sharing and feeder-buffer motivation baseline

This is a new controlled experiment, not a rerun or validation of previous
Zone/No-Zone pilots. Its question is whether sharing recovers useful service
capacity, and how transport and handoff costs affect that benefit.

## Fixed hardware

- Eight zones, eight shuttles, eight identical readers; one home shuttle and
  one reader per zone. Reader positions never change.
- Eight 16 m local rack lanes, 80 platter locations per zone (640 total), with
  zone junctions 1 m apart on a shared connecting trunk. Readers are at junctions.
- Every mode uses exclusive local lanes and an exclusive trunk. A shuttle
  reserves all needed resources for its entire route before leaving its dock.
  This conservative, coarse route model prevents conflicts by construction;
  it is not continuous-geometry validation or a calibrated Silica rail layout.
- Eight aggregate off-rail endpoint docking bays per zone, fixed across all
  comparisons. Waiting shuttles remain busy and retain their carried platter.
  Bay microgeometry/access is abstracted; do not interpret this as free unlimited
  holding or a proof of hardware feasibility. Bays are distinct from input slots.
- Input staging is the experimental factor: 0, 1, or 4 waiting slots per reader.
  The mounted platter and a single output slot do not count as input capacity.
- One fixed handoff/reader mechanism per reader in every setting. Handoff costs
  1 s. A shuttle leaves after handoff; load/mount/read/unload are serialized at
  the reader. B=0 requires the reader to be idle for direct handoff.
- Read completion is before unload. If output is occupied, unloading blocks
  the reader. A shuttle must pick up the completed platter and return it home.
  One platter cannot be fetched again until its return/place is complete.

Motion parameters and service times are controlled assumptions, not measured
new hardware specifications. `summary.json` expands the complete effective model.

## Sharing and dispatch

| Mode | Shuttle eligibility | Reader eligibility |
| --- | --- | --- |
| fixed | Home shuttle only | Home reader only |
| transport | Any shuttle in contiguous group of 2/4/8 zones | Home reader only |
| joint | Any shuttle in contiguous group of 2/4/8 zones | Any reader in same group |

Groups are defined by home zone IDs, not the shuttle's current physical
position. All groups have the same underlying connected hardware. Sharing
changes permission, never rail capacity or the conflict rules.

The controller dispatches output returns first (reader-ID order), then the
oldest feasible arrived request. A busy platter is not feasible. It chooses an
idle eligible shuttle by estimated pickup completion, then a reader by estimated
read completion. The estimate includes assigned but unread in-flight jobs, not
just the visible input queue. Unknown output-release delays are approximated.
This sequential heuristic is a baseline, not joint optimal scheduling.

Only one request is served per physical cycle. Online merge, predictive
prefetch, data cache, repositioning, relocation and new routing algorithms are
excluded to keep physical work constant across cases.

## Workload and pairing

An independent balanced saturated fixed/B=0 episode of 256 requests estimates a
finite-batch completion rate. All methods then use Poisson arrivals at 0.65 or
0.9 times this SAME rate. These factors are not guaranteed steady-state loads.

Each request reads 480 MiB at 60 MiB/s, plus explicit load/mount/unload costs.
Uniform arrivals choose home zones uniformly. In the hotspot pattern, the
middle third of arrivals puts 65% of requests into zones 3 and 4. Both patterns
use identical timestamps and local slot draws; all policies within one pattern
receive byte-for-byte identical request lists (hash checked).

The middle hotspot straddles sharing-group boundaries for group sizes 2 and 4.
This is a specific geography; do not claim a universal group-size trend without
moving the hotspot/group boundary in a follow-up experiment.

The full run contains 7 mode/group combinations × 3 buffer capacities ×
2 patterns × 2 rates × 3 seeds = **252 runs**, 480 requests per run.
The smoke run uses 96 requests and one seed = **84 runs**.
These finite episodes are for mechanism discovery, not production p99 inference.

## Run

```bash
.venv/bin/python -m unittest discover -s tests -p test_sharing_buffer_study.py -v
.venv/bin/python scripts/run_sharing_buffer_study.py --config experiments/sharing-buffer/smoke.json
.venv/bin/python scripts/run_sharing_buffer_study.py --config experiments/sharing-buffer/full.json
```

Use `--output-dir /path/to/new-directory` to preserve another run's output.
The expected runtime is seconds to a few minutes on a workstation, not a
multi-hour trace sweep. No external dataset or network is required.

## Evidence

- `runs.csv`: per-run metrics, trace hashes and controller runtime.
- `aggregate.csv`: arithmetic mean of run-level metrics and sample SD, not pooled
  p99 or confidence intervals.
- `summary.json`: calibration, full configuration, source hashes and validation.
- `fig1_latency.png`: p99 matrix for each pattern/rate.
- `fig2_latency_breakdown.png`: additive decomposition of MEAN request latency.
- `fig3_resource_costs.png`: resource time diagnostics; these cannot be added as
  request latency because resources operate concurrently.
- `fig4_timeline.png`: activity during 250 s from the first hotspot arrival.
- `audit-*`: full request/job/time/resource reservations for first-seed hotspot
  higher-load cases; regenerable and ignored by Git.

All requests must read exactly once and return; latency accounting, service
causality, single-resource exclusivity and input/output capacities are checked.
Tests also verify fixed-mode emulation with sharing group 1, hand-calculated
single-request latency, return-before-reuse and load/read overlap after handoff.

Excluded-work idle shuttle time is only an opportunity upper bound: an idle
shuttle might physically reach work outside its permission group, but doing so
is not guaranteed to help. Idle-reader-with-demand excludes demand-free idle,
but is not purely a measure of imminent platter shortage.
