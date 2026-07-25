# RQ2: Static-Zone Skew Threshold with Request Merge

## Purpose

This experiment fixes the static eight-zone architecture and changes only the fraction of logical requests assigned to one hot zone. Request merge remains enabled.

## Controlled setup

- Batch size: 10,000 logical requests.
- Request size: 64 MiB.
- Seeds: 10 paired runs per skew point.
- Hotspot width: one fixed zone for the complete batch.
- Fixed physical working set: 800 glass positions per zone.
- Local level and slot coordinates are paired across skew points.
- Work stealing and adaptive zones are disabled.

## Main findings

- Throughput first crosses 10% loss at 17.5% request skew; the measured hot-zone work share is 14.3%.
- Throughput first crosses 20% loss at 30.0% request skew; the measured hot-zone work share is 17.2%.
- At 80.0% request skew, logical throughput is 64.2% of the balanced case.
- At that endpoint, only 49.0% as many physical services remain after merge.
- The hot zone carries 38.0% of measured post-merge work, while 67.1% of static zone-time capacity is stranded.
- Mean throughput is monotonic non-increasing over the measured skew points.
- The steepest observed interval is 15.0% to 17.5% request skew, where normalized throughput drops 5.4 percentage points.
- The average decline per unit of added skew is 4.8x steeper before 25% request skew than after it.

## Interpretation

The throughput curve is the net result of two opposing effects: fixed ownership concentrates work in the hot zone, while repeated hot-glass accesses merge and reduce physical fetches. The measured points show an early steep decline followed by a flatter trend, not one isolated throughput cliff. A threshold reported here is therefore an operational crossing for this workload, not a universal queue-stability limit.

## Validation

- 110 runs preserve logical request count and bytes across merge.
- Every compared skew point uses the same request count, request size, geometry, timing, and paired seeds.

## Figure guide

- `fig1_throughput_vs_request_skew`: normalized logical throughput and 10%/20% loss lines.
- `fig2_merge_and_work_skew`: physical-service reduction and measured hot-zone shares.
- `fig3_ownership_cost_vs_skew`: stranded capacity and ownership slowdown.
