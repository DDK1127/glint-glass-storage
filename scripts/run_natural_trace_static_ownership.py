from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from glass_sim.natural_trace_static_ownership import (
    load_natural_trace_static_ownership_config,
    run_natural_trace_static_ownership,
    write_natural_trace_static_ownership_outputs,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Replay the natural LUN0 trace under exact static ownership and "
            "compare it with a perfectly balanced throughput lower bound."
        )
    )
    parser.add_argument(
        "--config",
        default="experiments/natural-trace-static-ownership/full.json",
    )
    args = parser.parse_args()

    config = load_natural_trace_static_ownership_config(args.config)
    result = run_natural_trace_static_ownership(config)
    write_natural_trace_static_ownership_outputs(config, result)
    print(
        json.dumps(
            {
                "output_dir": str(config.output_dir),
                "read_requests": result.source["read_requests"],
                "window_rows": len(result.window_rows),
                "validation_passed": result.validation["passed"],
                "findings": result.findings,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
