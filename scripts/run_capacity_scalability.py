from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path("results/.mplconfig").resolve())
)
os.environ.setdefault(
    "XDG_CACHE_HOME", str(Path("results/.cache").resolve())
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from glass_sim.capacity_scalability import (
    load_capacity_scalability_config,
    run_capacity_scalability,
    write_capacity_scalability_outputs,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Measure fixed-resource performance as glass capacity and "
            "physical rack footprint grow."
        )
    )
    parser.add_argument(
        "--config",
        default="experiments/capacity-scalability/full.json",
    )
    args = parser.parse_args()

    config = load_capacity_scalability_config(args.config)
    result = run_capacity_scalability(config)
    write_capacity_scalability_outputs(config, result)
    print(
        json.dumps(
            {
                "output_dir": str(config.output_dir),
                "runs": len(result.run_rows),
                "aggregate_rows": len(result.aggregate_rows),
                "validation_passed": result.validation["passed"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
