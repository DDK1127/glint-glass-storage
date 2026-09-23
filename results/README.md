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
| `zone-nozone-natural-arrivals/` | Paired policy latency under original Azure timestamps; see the documented holding-pocket assumptions |
| `zone-nozone-natural-arrivals-4-64/` | Denser 4/8/16/32/64 m raw-arrival Zone/No-Zone sweep |
| `zone-nozone-comparison-4-64/` | Paired closed-batch companion for service phases, slowest-zone drain, and coordination costs |
| `no-zone-conflict/` | Post-hoc continuous-time conflict-exposure pilot for nearest-idle No-Zone dispatch |
| `windowed-cbs/` | Static, Greedy No-Zone, and bounded small-window CBS over paired closed-batch work |
| `no-zone-virtual-ideal/` | Collision-free Virtual No-Zone comparison against Static and Greedy baselines |
| `buffered-32rack-policy-comparison/` | Fixed 32-rack feeder-buffer pilot comparing 8-zone end-to-end, rack-local, and shared movement |
| `shuttle-following-demo/`, `shuttle-following-service/` | Same-direction clearance and pickup-to-reader service examples |
| `shuttle-yield-demo/` | Two-shuttle abstract bypass/yield example |
| `presentations/glint_zone_nozone_story_en.pptx` | Editable English Zone/No-Zone research-story deck with validated experiment figures |

Superseded Zipf, artificial temporal-skew, and batch-skew outputs moved to
`archive/results/`. Matching active configurations live in `experiments/`;
entry points live in `scripts/`.
