#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json

from glass_sim.lun_address_static_zone import (
    load_lun_address_static_zone_config,
    run_lun_address_static_zone,
    write_lun_address_static_zone_outputs,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure static-zone skew under fixed contiguous LUN address mapping."
    )
    parser.add_argument(
        "--config",
        default="experiments/lun-address-static-zone/full.json",
    )
    args = parser.parse_args()
    config = load_lun_address_static_zone_config(args.config)
    result = run_lun_address_static_zone(config)
    write_lun_address_static_zone_outputs(config, result)
    print(
        json.dumps(
            {
                "output_dir": str(config.output_dir),
                "logical_requests": result.summary["logical_request_count"],
                "physical_tasks": result.summary["physical_task_count"],
                "validation_passed": result.validation["passed"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
