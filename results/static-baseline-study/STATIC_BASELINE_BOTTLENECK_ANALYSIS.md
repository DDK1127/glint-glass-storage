# Static-Zone Baseline Bottleneck Analysis

## Research purpose

This study characterizes the strict static-zone baseline before introducing any adaptive policy. It asks two separate questions: what makes one glass service expensive, and what prevents the full panel from using its aggregate resources under spatial skew?

## Controlled setup

- Layout: 4 rows x 2 sides, 8 static zones.
- Each zone owns one shuttle and one local reader.
- A shuttle remains reserved for direct fetch, read, unload, and return; there is no feeder buffer.
- Batch: 10,000 logical requests, 64 MiB/request.
- Seeds: 20260710, 20260711, 20260712, 20260713, 20260714.
- Local level/slot coordinates are paired across skew cases; only zone assignment changes.
- Request merge is the default behavior: all requests to the same physical glass are coalesced before scheduling.
- Every compared skew case is evaluated from its resulting merged glass-task set.

## Observation 1: fixed-zone concentration controls usable parallelism

A separate paired experiment starts from the same 640 unique active glass tasks in every case. The task sizes and local level/slot coordinates are unchanged; only the number of fixed zones that own those tasks changes.

Concentrating the tasks in 1 fixed zone yields a mean makespan of 5.72 h and uses 12.5% of panel zone-time capacity. Distributing the same task templates across 8 zones changes these values to 0.74 h and 96.6%.

The total productive-cycle work varies by only 0.1% across the concentration sweep. The experiment therefore isolates how many fixed owners can serve the active set, rather than changing logical popularity or merge opportunities.

> The structural issue is fixed-zone ownership: when active work belongs to only a subset of zones, the remaining resources cannot contribute under strict operation.

## Observation 2: merge defines the physical workload

The balanced and heavy-skew batches both contain 10,000 logical requests, but after default merge they contain approximately 5066 and 2487 physical glass services, respectively. Repeated accesses in the finite hot working set share a single fetch, while the merged bytes are still read by the reader.

The scheduler should therefore reason about merged glass tasks, not raw request count. Merge is part of the workload semantics, not an alternative policy.

## Observation 3: static partitioning works when merged demand is balanced

At the balanced endpoint, mean makespan is 5.97 h and the panel converts 98.0% of its zone-time capacity into active service cycles.

This is the favorable case for static zones: each shuttle-reader pair receives a comparable merged glass-task queue, so isolation gives predictable motion without stranding much capacity.

## Observation 4: one merged glass service remains robotics-heavy

Under heavy skew, the average active cycle consists of 51.1% shuttle movement, 33.9% fixed pick/load/unload/place operations, and 14.9% reader transfer.

Movement plus fixed handling still accounts for most of a glass service. Reader share rises when more logical requests merge into each hot glass, but a faster reader alone cannot remove the ownership imbalance between zones.

## Observation 5: spatial concentration strands otherwise usable resources

When the hot region receives 80.0% of logical requests, mean makespan grows from 5.97 h to 9.27 h (1.55x).
Logical throughput falls to 64.4% of the balanced case, and 67.1% of total zone-time capacity is idle while hot work remains.
The static makespan is 3.04x the work-conserving lower bound computed from the same merged active-cycle work.

This is especially important because the heavy-skew batch contains fewer physical glass services than the balanced batch, yet still finishes later. The limiting factor is where the merged tasks are owned, not simply how many tasks exist globally.

## Bottleneck hierarchy

1. Per glass service: shuttle movement and fixed mechanical operations dominate reader transfer.
2. Balanced system: static zones use aggregate capacity efficiently; local mechanical cost determines throughput.
3. Skewed system: hot-zone serialization and stranded cold-zone capacity dominate the makespan.
4. Reader-bound limit: if reader service is made sufficiently slow, scheduling flexibility will no longer improve aggregate throughput.

## Transition to the research problem

The static baseline partitions the complete physical capacity before it observes which platters are active. The experiment shows that this is harmless when demand is balanced, but it ties batch completion to the busiest owner when the active working set is spatially skewed.

> The next research question is not simply how to make shuttles faster. It is whether the scheduler can partition the active glass tasks, rather than the full storage space, so that hot work can use otherwise idle shuttle-reader pairs without giving up spatial locality and predictable traffic.

## Figure guide

- `fig1_static_performance_vs_skew`: batch-level performance degradation as hot share increases.
- `fig2_ownership_imbalance`: static efficiency and distance from the work-conserving lower bound.
- `fig3_stranded_capacity`: productive versus stranded zone-time capacity.
- `fig4_local_vs_system_bottleneck`: separates per-service cost from system-level ownership loss.
- `fig5_zone_completion_profiles`: shows balanced versus hot-zone completion directly.
- `fig6_hotspot_width_sensitivity`: shows whether the same hot demand is concentrated in one or several zones.
- `fig7_research_story_panel`: condensed paper-ready motivation panel.
- `fig8_active_zone_concentration`: paired active tasks concentrated in 1, 2, 4, or 8 fixed zones.
- `fig9_fixed_zone_activity_timeline`: productive and stranded intervals for each fixed owner.

## Evidence boundaries

- Shared-pool, work-stealing, and proposed virtual-zone policies are intentionally not included here.
- Collision is absent because strict zones contain one shuttle each and do not cross boundaries.
- The direct serial cycle does not model feeder prefetch or shuttle-reader pipelining.
- The workload is synthetic and paired; trace-driven temporal validation remains future work.
