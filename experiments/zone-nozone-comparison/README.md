# Zone / no-zone advisor-discussion experiment

The primary runner preserves the real Azure request arrival timestamps:

```bash
.venv/bin/python scripts/run_zone_nozone_trace.py --workers 4
```

The denser 4--64 m sweep keeps the earlier 2/16/64 m outputs intact:

```bash
.venv/bin/python scripts/run_zone_nozone_trace.py \
  --config experiments/zone-nozone-comparison/sweep-4-64-natural.json \
  --workers 4
.venv/bin/python scripts/run_zone_nozone_comparison.py \
  --config experiments/zone-nozone-comparison/sweep-4-64.json
```

It uses the physical/timing parameters and ten seeds in `full.json`, with outputs
under `results/zone-nozone-natural-arrivals/`. `--smoke` uses one seed and 16 m
while retaining all 100,000 requests and 640 mapped platters.

The older `run_zone_nozone_comparison.py` is a closed-batch diagnostic draft.
It does not replay the original timestamps and is not the primary evidence
for a natural-workload story. Its `smoke.json` also changes platter packing
to 64 platters and must not be treated as a shortened full trace experiment.
It is retained as the causal companion experiment because both policies serve
exactly the same batch-merged physical platter tasks. Its new phase breakdown
separates fetch, delivery, reader, return, fixed handling, queueing, and
conflict-avoidance time.

Both policies preserve logical requests, object versions and bytes. They
share seeded physical placement. Only queued, arrived requests on the same
platter are merged when dispatch occurs; future requests require a later
service. The physical platter is unavailable until returned. Consequently,
merge opportunities and physical service counts may differ across policies.

## Model boundary

- Eight shuttles and eight readers; four of each per disconnected panel side.
- Static ownership uses four two-level bands per side and assumes perfect
  traffic isolation. Geometric inter-zone overlap is not checked for static.
- No-zone chooses the nearest currently idle shuttle on the reachable side,
  by Manhattan path distance. Busy robots cannot receive another job.
- Readers use nearest-distance selection, with availability and reader ID
  breaking ties. Committed operations reserve the reader.
- Whole jobs are planned against existing reservations. Direct or single
  intermediate-level routes are considered; waiting and detouring change
  future dispatch times.
- **Optimistic off-rail holding is assumed**, including while waiting at
  platter and reader locations. Capacity is unlimited and entry/exit is
  instantaneous. Idle robots do not block rails. This is not a calibrated
  hardware safety model, and the assumption must accompany all figures.
- No-zone verification checks committed rail trajectories, not the physical
  feasibility of the assumed holding pockets. No claim of collision-free
  production execution is made.
- Controller Python runtime is recorded separately and is not simulated
  controller latency.

## Observation outputs

- `fig3_service_phase_breakdown`: one complete physical platter service under
  paired closed-batch work.
- `fig4_isolation_vs_coordination`: static slowest-zone/idle cost versus
  no-zone locality, holding, detour, and reader-queue cost.
- `fig5_nozone_coordination_location`: where no-zone coordination enters the
  fetch-delivery-reader-return pipeline.
- Natural-arrival `fig5_request_latency_breakdown`: request queueing before
  dispatch versus post-dispatch service. Return/place are excluded from the
  request's own completion but still delay later work.

No hand-adjusted request skew or arrival-rate scaling is used. Object packing,
geometry, speed and clearance remain explicit experimental assumptions.

The current scheduler is documented as the
[Greedy No-Zone baseline](../../docs/research/greedy-no-zone-baseline.md).
