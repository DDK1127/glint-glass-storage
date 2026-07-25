# RQ1: Natural Trace Skew Characterization

## Research question

> In natural timestamp order, does post-merge physical service demand remain spatially skewed at realistic request-count and time scales?

## Experiment contract

- Source trace: `data/2016022211-LUN0.csv`.
- Reads: 1,399,055 over 60.0 minutes.
- Request order: original timestamps after explicitly sorting the raw file; no artificial hot-zone reordering.
- Count windows: 100, 500, 1,000, 5,000, 10,000, 20,000, 50,000 requests.
- Time windows: 1s, 5s, 15s, 30s, 60s, 120s, 300s, 600s, 900s.
- Merge scope: independently within every measured window; repeated accesses to one mapped platter become one physical service with summed bytes.
- Work metric: estimated local platter-to-reader round trip, fixed pick/load/unload/place time, and reader transfer time. Inter-task repositioning is omitted from the characterization proxy.

## Placement assumptions

The trace contains LUN offsets, not the real mapping from data to Silica platters and zones. Results are therefore reported under two explicit assumptions:

1. `Randomized hash`: three stable hash seeds distribute 64 MiB stripes across 6,400 panel positions. This matches a no-placement-locality assumption and reports seed variation.
2. `Contiguous LBA`: logical block ranges map contiguously across the panel. This is a sensitivity bound, not a claim about the deployed Silica placement.

## Primary findings

Under randomized placement, the P95 busiest-zone post-merge work share is 47.1% for 100-request windows, 17.7% for 5,000-request windows, and 14.1% for 50,000-request windows.
At the primary 5,000-request scale, 0.0% of windows exceed the configured 25% work-share threshold.
For 1.0-minute windows, the randomized-placement P95 busiest-zone work share is 14.8%.
At 5,000 requests, placement changes the P95 result from 17.7% under randomized hashing to 55.6% under contiguous-LBA mapping.

## RQ1 interpretation

Classification: `short_burst_and_placement_correlated`.

The trace supports a short-timescale burst problem under randomized placement, but it does not support a claim of severe persistent imbalance at the primary 5,000-request or 60-second scales. Stronger long-lived skew appears only when LBA locality is preserved by the placement assumption. The defensible motivation is therefore conditional: adaptation must react quickly to bursts, or exploit observed placement-access correlation; static zones are not shown to be universally imbalanced.

## Validation

- Window conservation checks: 64 placement/window configurations passed exact logical-request and byte conservation.
- Merge cardinality: passed against the existing batch-wide merge implementation.
- Work-share proxy versus full static-zone simulation: mean absolute error 0.21 percentage points; maximum 1.97 points across 32 sampled windows.

## Evidence boundary

- This is one one-hour LUN trace, not a multi-dataset production prevalence study.
- Zone-level skew is conditional on synthetic placement because the trace does not expose real platter placement.
- Larger windows have fewer samples; P95 values at the longest time scales are descriptive rather than statistically stable.
- Empty time buckets are excluded; reported time-window distributions characterize periods containing read activity.
- The capacity metric is a fixed-owner work-balance proxy, not an online throughput prediction.
- The study characterizes natural demand; it does not yet model Microsoft work stealing or the proposed adaptive policy.

## Decision rule for the research story

- If randomized-placement post-merge skew remains high across realistic scales, proceed with natural static-stranding and work-stealing experiments.
- If skew appears only at short scales, frame the problem as burst/tail adaptation and make control-epoch duration central.
- If skew is low under randomized placement but high only under contiguous placement, the motivation is placement-correlated access, not universal trace skew.

## Figure guide

- `fig1_natural_skew_vs_window`: P95 post-merge work skew versus count/time scale.
- `fig2_logical_vs_post_merge_work`: logical request skew versus physical service-demand skew.
- `fig3_natural_zone_activity_heatmap`: zone activity over natural trace order.
- `fig4_capacity_and_hotspot_frequency`: fixed-owner capacity proxy and hot-window frequency.
- `fig5_placement_sensitivity`: sensitivity to the unavailable platter-placement mapping.
