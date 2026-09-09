# Current Experiments

Each study has a quick `smoke.json` configuration and a retained-result
`full.json` configuration.

| Directory | Purpose | Runner |
| --- | --- | --- |
| `azure-blob-preprocessing/` | Stable read-only canonicalization of the Azure Functions Blob trace | `scripts/preprocess_azure_blob_trace.py` |
| `azure-blob-batch/` | Deterministic head-100k pilot batch paired with the existing LUN0 batch | `scripts/extract_azure_blob_batch.py` |
| `azure-static-zone-pilot/` | Static ownership sensitivity on the Azure head-100k batch | `scripts/run_azure_static_zone_pilot.py` |
| `lun-address-static-zone/` | Fixed contiguous LUN-address mapping across eight static zones | `scripts/run_lun_address_static_zone.py` |
| `rq1-natural-skew/` | Natural-order post-merge skew and placement sensitivity | `scripts/run_natural_trace_skew.py` |
| `static-baseline/` | Strict fixed-zone ownership characterization | `scripts/run_static_baseline_study.py` |
| `rq2-skew-threshold/` | Request-merge throughput curve under increasing single-zone skew | `scripts/run_skew_threshold_study.py` |
| `work-stealing/` | Hotspot and single-helper distance tradeoff | `scripts/run_static_zone_work_stealing_study.py` |
| `adaptive-zone-upper-bound/` | Paired equal-size and batch-oracle adaptive rectangular zones | `scripts/run_adaptive_zone_study.py` |
| `static-ownership-motivation/` | Controlled causal study of unequal post-merge work under equal-area ownership | `scripts/run_static_ownership_motivation.py` |
| `static-ownership-threshold/` | Throughput-loss crossings under increasing post-merge owner concentration | `scripts/run_static_ownership_threshold.py` |
| `capacity-scalability/` | Fixed-reader/shuttle capacity growth with fixed- and growing-footprint controls | `scripts/run_capacity_scalability.py` |
| `azure-capacity-scalability/` | Capacity growth using Azure Blob identities, reuse, and object sizes | `scripts/run_azure_capacity_scalability.py` |

`adaptive-zone-upper-bound/dense.json` increases resolution to 40 skew points,
including 1% spacing across the observed 30%-50% layout-transition region.

Configuration paths are resolved relative to the repository root, so the
runner can be invoked from another working directory when given an absolute
config path.
