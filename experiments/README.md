# Current Experiments

Each study has a quick `smoke.json` configuration and a retained-result
`full.json` configuration.

| Directory | Purpose | Runner |
| --- | --- | --- |
| `rq1-natural-skew/` | Natural-order post-merge skew and placement sensitivity | `scripts/run_natural_trace_skew.py` |
| `static-baseline/` | Strict fixed-zone ownership characterization | `scripts/run_static_baseline_study.py` |
| `rq2-skew-threshold/` | Request-merge throughput curve under increasing single-zone skew | `scripts/run_skew_threshold_study.py` |
| `work-stealing/` | Hotspot and single-helper distance tradeoff | `scripts/run_static_zone_work_stealing_study.py` |
| `adaptive-zone-upper-bound/` | Paired equal-size and batch-oracle adaptive rectangular zones | `scripts/run_adaptive_zone_study.py` |

Configuration paths are resolved relative to the repository root, so the
runner can be invoked from another working directory when given an absolute
config path.
