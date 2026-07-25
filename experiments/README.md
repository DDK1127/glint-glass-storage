# Current Experiments

Each study has a quick `smoke.json` configuration and a retained-result
`full.json` configuration.

| Directory | Purpose | Runner |
| --- | --- | --- |
| `rq1-natural-skew/` | Natural-order post-merge skew and placement sensitivity | `scripts/run_natural_trace_skew.py` |
| `static-baseline/` | Strict fixed-zone ownership characterization | `scripts/run_static_baseline_study.py` |
| `work-stealing/` | Hotspot and single-helper distance tradeoff | `scripts/run_static_zone_work_stealing_study.py` |

Configuration paths are resolved relative to the repository root, so the
runner can be invoked from another working directory when given an absolute
config path.
