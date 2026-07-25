---
marp: true
title: From Batch-Level Skew to Adaptive Service Zones
description: English research presentation draft
paginate: true
style: |
  section { font-family: Inter, Arial, sans-serif; color: #233044; padding: 52px 64px; }
  h1 { color: #233044; font-size: 36px; }
  h2 { color: #2F66AD; font-size: 27px; }
  p, li { font-size: 21px; line-height: 1.35; }
  strong { color: #A9443C; }
  .small { font-size: 16px; color: #657087; }
  .panel-half { width: 568px; height: 400px; overflow: hidden; margin: 4px auto 8px; }
  .panel-half img { width: 1136px; height: 400px; max-width: none; display: block; }
  .panel-right img { transform: translateX(-568px); }
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 36px; }
  .callout { border-left: 5px solid #7256B5; padding: 10px 18px; background: #F1ECFF; }
---

# From Batch-Level Skew to Adaptive Service Zones

## Rethinking fixed shuttle ownership in Project Silica

**Question:** How can a glass library adapt its service regions to a changing active workload without giving up spatial locality?

<p class="small">Presentation draft based on the current trace-derived and collision-free simulation results.</p>

<!--
Speaker note:
This talk starts with a controlled observation of batch-level skew. It then explains why the evidence is limited, why Microsoft uses static partitions, where fixed ownership becomes restrictive, and how adaptive service zones form the research direction.
-->

---

# A Controlled View of Batch-Level Access Skew

- We replay the **same 100,000 trace requests** in 20 consecutive batches.
- Each batch contains **5,000 logical requests**.
- Only batch ordering changes:
  - Normal timestamp order
  - 50% target hot-zone share
  - 80% target hot-zone share
- Request merging is performed **within each batch**.

<div class="callout">The experiment controls skew to study its impact. It does not claim that these exact skew levels naturally occur in every workload.</div>

<!--
Speaker note:
The request multiset, offsets, sizes, and physical mapping are unchanged. We deliberately reorder requests to create different temporary hot zones. Therefore, this experiment is causal evidence about what skew can do under the model, not prevalence evidence about real production workloads.
-->

---

# Logical Skew Is Not Physical Work Skew

<div class="panel-half panel-left"><img src="../../outputs/trace-batch-skew-static/figures/fig1_batch_skew_and_capacity.png" /></div>

- More logical requests can merge into fewer physical glass services.
- At the P95 batch, an 80% logical hot-zone share becomes **64.1% post-merge active work**.

<!--
Speaker note:
The left panel shows how uneven each batch is. Blue represents logical requests and red represents post-merge active work. The difference matters because shuttle load is driven by unique glass services and mechanical work, not request count alone.
-->

---

# Under Fixed Ownership, Skew Strands Capacity

<div class="panel-half panel-right"><img src="../../outputs/trace-batch-skew-static/figures/fig1_batch_skew_and_capacity.png" /></div>

- Useful shuttle-reader capacity falls from **85.1%** to **35.4%** and **22.1%**.
- Cold zones finish early while the hot-zone owner remains on the critical path.

<!--
Speaker note:
The right panel converts batch skew into system impact. Under strict ownership, idle shuttle-reader pairs cannot serve the hot queue. Because batches drain sequentially, unused capacity in the current batch cannot be recovered by future work.
-->

---

# The Performance Consequence

| Workload | Makespan | Throughput | P99 latency |
| --- | ---: | ---: | ---: |
| Normal order | 15.29 h | 1.817 req/s | 0.79 h |
| Moderate skew | 32.50 h | 0.855 req/s | 1.75 h |
| Severe skew | 42.79 h | 0.649 req/s | 2.39 h |

- Severe controlled skew increases makespan by **2.80×**.
- The bottleneck is **where active work is owned**, not a lack of aggregate resources.

<!--
Speaker note:
These numbers are produced by the sequential-batch model. They establish the mechanism: completion is tied to the busiest static owner while other resources wait.
-->

---

# Evidence Boundary: Batch Size Matters

- The 50% and 80% skew levels are **experimentally controlled**.
- The observed impact depends on this dataset, its locality, and merge behavior.
- A larger batch may combine more independent requests and **smooth short-lived skew**.
- However, this is not a universal monotonic rule:
  - persistent spatial hotspots may remain skewed;
  - merging can change physical work differently from logical request counts;
  - online arrivals may overlap instead of waiting for a batch barrier.

<div class="callout">Batch size must be swept explicitly before claiming how often real workloads expose this problem.</div>

<!--
Speaker note:
This slide prevents us from overclaiming. Larger aggregation windows often smooth transient variation, but the effect is dataset-dependent. We still need a batch-size and online-arrival sensitivity study.
-->

---

# Why Microsoft Uses Static Partitions

- The panel is divided into rectangular logical partitions.
- Each partition contains one shuttle and at least one read-drive slot.
- During normal operation, a shuttle remains inside its partition.

**This is a deliberate engineering tradeoff:**

- shorter and more predictable paths;
- simpler real-time traffic management;
- lower congestion exposure at read drives and partition boundaries.

<!--
Speaker note:
Static partitioning is not simply a bad design. Microsoft uses it because unrestricted global movement makes real-time routing and congestion control harder. Our work must preserve these benefits when the workload is balanced.
-->

---

# Where Fixed Ownership Becomes Restrictive

Static partitions assign service responsibility according to **panel geometry**, while demand follows a **time-varying access pattern**.

When active requests concentrate in a few physical regions:

- hot-zone shuttles and readers remain busy;
- cold-zone resources become idle;
- completion is determined by the busiest owner;
- fixed service regions cannot follow a moving or bursty hotspot.

<div class="callout">The mismatch is not partitioning itself. It is long-lived, geometry-driven ownership that cannot adapt to the active working set.</div>

<!--
Speaker note:
This framing is stronger than saying that static zones remove the purpose of shuttles. Static zones intentionally limit flexibility. The research gap is whether service ownership can adapt without returning to uncontrolled global traffic.
-->

---

# Work Stealing Restores Some Flexibility

Project Silica uses work stealing as a load-imbalance fallback:

- the controller monitors data volume across partitions;
- a lightly loaded shuttle may temporarily enter an overloaded partition;
- the shuttle uses shortest-path routing outside its normal region.

In Microsoft's skew evaluation:

- tail completion time improves from **over 21 h to 11.5 h**;
- tail travel time increases from **29.4 s to 76 s**.

<!--
Speaker note:
Work stealing is an effective and necessary baseline. It recovers idle capacity, but it does so reactively and introduces cross-partition movement. Microsoft explicitly notes that movement outside a partition may create additional congestion.
-->

---

# The Remaining Work-Stealing Cost

<div class="two-col">
  <div><img src="../diagrams/hot-cold-zone-distance.png" style="width:100%; margin-top:22px" /></div>
  <div>
    <ul>
      <li>A lightly loaded helper may be far from the hot zone.</li>
      <li>Assistance includes repositioning, platter transport, and return travel.</li>
      <li>Intermediate zones and hot-zone ingress may experience additional traffic.</li>
    </ul>
  </div>
</div>

<!--
Speaker note:
The coldest partition is not necessarily the best helper. Helper value also depends on distance, intermediate-zone load, platter round-trip cost, and the number of helpers entering the hot region.
-->

---

# Key Insight: Load Alone Is Not Enough

In our collision-free single-helper experiment:

| Helper | Hotspot makespan reduction | Extra aggregate travel |
| --- | ---: | ---: |
| Nearby Zone 2 | 40.6% | 0.68 h |
| Distant Zone 7 | 27.4% | 1.91 h |

```text
Net assistance value
= completion-time reduction
- cross-zone movement
- interference and congestion risk
```

<p class="small">The current model measures direct movement cost; route-conflict waiting and multi-helper congestion remain future work.</p>

<!--
Speaker note:
This result supports locality-aware helper selection, but it is not yet evidence about collision delay. The next model must add intermediate-zone load and route-conflict waiting.
-->

---

# Proposed Direction: Adaptive Service Zones

The goal is **not unrestricted per-request shuttle movement**.

Instead, adapt service responsibility to the active workload:

- resize or reshape service regions at each control epoch;
- assign more shuttle-reader capacity to active hot regions;
- avoid reserving full service capacity for inactive cold regions;
- keep each region spatially compact;
- bound cross-zone distance and concurrent helpers;
- use hysteresis to avoid frequent reconfiguration.

<!--
Speaker note:
The physical glass remains in place. We change logical service ownership, not data placement. Within an epoch, assignments remain stable so that routing stays structured and predictable.
-->

---

# Research Hypothesis

**Request-adaptive service zones can recover stranded capacity with less cross-region travel than reactive work stealing.**

Required comparison on identical merged glass tasks:

1. Strict static partitions
2. Microsoft-style work stealing
3. Adaptive service zones
4. Ideal shared-pool upper bound

Primary metrics:

- makespan, throughput, and P95/P99 latency;
- shuttle-reader utilization balance;
- cross-zone travel and conflict waiting;
- reconfiguration cost and stability.

<!--
Speaker note:
The proposed method is convincing only if it recovers imbalance losses while preserving enough locality to avoid the congestion behavior of unconstrained global sharing.
-->

---

# Takeaway

1. Controlled batch skew shows how fixed ownership can strand capacity.
2. The result is batch- and dataset-dependent, so sensitivity analysis is required.
3. Static partitions provide valuable locality and congestion control.
4. Work stealing restores flexibility, but adds reactive cross-zone movement.
5. The opportunity is to make **service regions adapt to active requests**, while keeping movement structured and bounded.

> Adapt ownership to the workload, rather than forcing every workload into the same fixed ownership map.
