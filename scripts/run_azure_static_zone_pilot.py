from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from glass_sim.azure_static_zone_pilot import (
    load_azure_static_zone_pilot_config,
    run_azure_static_zone_pilot,
    write_azure_static_zone_pilot_outputs,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure static-zone skew on the Azure head-100k pilot batch."
    )
    parser.add_argument(
        "--config",
        default="experiments/azure-static-zone-pilot/full.json",
    )
    args = parser.parse_args()
    config = load_azure_static_zone_pilot_config(args.config)
    result = run_azure_static_zone_pilot(config)
    write_azure_static_zone_pilot_outputs(config, result)
    print(
        json.dumps(
            {
                "output_dir": str(config.output_dir),
                "runs": len(result.run_rows),
                "validation_passed": result.validation["passed"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
