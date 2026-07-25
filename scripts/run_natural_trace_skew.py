from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("MPLCONFIGDIR", str(Path("results/.mplconfig").resolve()))
os.environ.setdefault("XDG_CACHE_HOME", str(Path("results/.cache").resolve()))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from glass_sim.natural_trace_skew import (
    load_natural_trace_skew_config,
    run_natural_trace_skew_study,
    write_natural_trace_skew_outputs,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Characterize natural post-merge spatial skew across count and time windows."
    )
    parser.add_argument(
        "--config",
        default="experiments/rq1-natural-skew/full.json",
    )
    args = parser.parse_args()

    config = load_natural_trace_skew_config(args.config)
    study = run_natural_trace_skew_study(config)
    write_natural_trace_skew_outputs(config, study)
    print(
        json.dumps(
            {
                "output_dir": str(config.output_dir),
                "read_requests": study.source_stats["read_requests"],
                "trace_span_minutes": study.source_stats["trace_span_s"] / 60.0,
                "window_rows": len(study.window_rows),
                "validation_passed": study.validation["passed"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
