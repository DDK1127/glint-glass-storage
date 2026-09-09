# Retained Experiment Results

Only current, full experiment results are retained here. Smoke runs and
superseded model iterations should be regenerated rather than accumulated.

| Directory | Purpose |
| --- | --- |
| `natural-trace-skew-rq1/` | RQ1 natural-order, post-merge zone-skew characterization and placement sensitivity |
| `static-baseline-study/` | Corrected strict static-zone characterization baseline |
| `rq2-skew-threshold/` | Dense request-skew sweep with merge, throughput crossings, and ownership cost |
| `static-zone-work-stealing-study/` | 8-zone hotspot and one-helper distance motivation study |
| `adaptive-zone-upper-bound/` | Equal-size static zones versus physically contiguous batch-oracle adaptive zones |
| `adaptive-zone-dense-sweep/` | Forty-point skew sweep resolving discrete adaptive-boundary transitions |
| `static-ownership-motivation/` | Equal-area static ownership causal mechanism with paired unique and merged workloads |
| `static-ownership-threshold/` | Owner-concentration sweep and observed throughput-loss crossings |
| `natural-trace-static-ownership/` | LUN0 owner-level work and throughput under fixed placement |
| `lun-address-static-zone/` | Contiguous LUN-address mapping into eight fixed zones |
| `azure-static-zone-pilot/` | Azure head-100k static-zone placement sensitivity |
| `capacity-scalability/` | Fixed-resource capacity growth and per-platter time decomposition |
| `azure-capacity-scalability/` | Capacity growth using Azure request identity, reuse, and object sizes |

Superseded Zipf, artificial temporal-skew, and batch-skew outputs moved to
`archive/results/`. Matching active configurations live in `experiments/`;
entry points live in `scripts/`.
