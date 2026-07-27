from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("MPLCONFIGDIR", str(Path("results/.mplconfig").resolve()))
os.environ.setdefault("XDG_CACHE_HOME", str(Path("results/.cache").resolve()))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from glass_sim.static_ownership_threshold import (
    load_static_ownership_threshold_config,
    run_static_ownership_threshold,
    write_static_ownership_threshold_outputs,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure static-ownership throughput loss as one owner concentrates work."
    )
    parser.add_argument(
        "--config",
        default="experiments/static-ownership-threshold/full.json",
    )
    args = parser.parse_args()

    config = load_static_ownership_threshold_config(args.config)
    result = run_static_ownership_threshold(config)
    write_static_ownership_threshold_outputs(config, result)
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
