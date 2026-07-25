from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("MPLCONFIGDIR", str(Path("results/.mplconfig").resolve()))
os.environ.setdefault("XDG_CACHE_HOME", str(Path("results/.cache").resolve()))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from glass_sim.adaptive_zone_study import (
    load_adaptive_zone_study_config,
    run_adaptive_zone_study,
    write_adaptive_zone_outputs,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare static equal-size zones with adaptive work-balanced zones."
    )
    parser.add_argument(
        "--config",
        default="experiments/adaptive-zone-upper-bound/full.json",
    )
    args = parser.parse_args()

    config = load_adaptive_zone_study_config(args.config)
    result = run_adaptive_zone_study(config)
    write_adaptive_zone_outputs(config, result)
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
