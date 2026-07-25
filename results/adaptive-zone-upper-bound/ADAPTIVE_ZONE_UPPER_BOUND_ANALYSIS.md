# Static Equal-size vs. Adaptive Work-balanced Zones

## Research question

With the same merged workload, eight shuttles, and eight active readers, how much capacity does equal-area static ownership strand, and how much can physically contiguous adaptive boundaries recover?

## Controlled setup

- 10,000 logical requests per batch, 64 MiB each.
- 10 paired seeds per skew point.
- Batch-wide platter merge is always enabled.
- Four positive-height contiguous rectangular zones per panel side.
- No work stealing, prediction, Zipf distribution, or reconfiguration cost.
- Adaptive boundaries observe the complete merged batch and therefore represent an upper bound.

## Main results

- At balanced 12.5% request share, adaptive drain speedup is 1.000x and throughput improvement is 1.000x.
- At 80.0% request skew, adaptive drain speedup is 2.235x and throughput improvement is 2.236x.
- Static stranded capacity is 67.1%; adaptive stranded capacity is 28.1%.
- The system-drain gap to each policy's own work-conserving lower bound changes from 3.04x to 1.39x.

## Interpretation

The paired trace check ensures that any difference comes from ownership and reader assignment, not from fewer platter services. The adaptive result is intentionally an upper bound: a later study must account for boundary movement, control frequency, and time-varying workloads before claiming an implementable online gain.

## Validation

- 60 paired runs preserved merged platter IDs, logical request count, bytes, side, level, and slot.
- Every layout contains eight non-overlapping zones, eight shuttles, and eight active readers.
- The equal-size static layout is a legal optimizer candidate.

## Figure guide

- `fig1_static_vs_adaptive_performance`: throughput and full-cycle drain time.
- `fig2_imbalance_and_stranded_capacity`: exact zone-work imbalance and idle capacity.
- `fig3_gap_to_work_conserving_ideal`: system drain relative to each policy's lower bound.
- `fig4_representative_layout`: equal-size and adaptive panel layouts at maximum skew.
