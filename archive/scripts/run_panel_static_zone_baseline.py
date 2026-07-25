from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("MPLCONFIGDIR", str(Path("outputs/.mplconfig").resolve()))
os.environ.setdefault("XDG_CACHE_HOME", str(Path("outputs/.cache").resolve()))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from glass_v2.panel_static_zone import (
    load_panel_static_zone_config,
    run_panel_static_zone,
    write_panel_static_zone_outputs,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the panel static-zone direct-service baseline.")
    parser.add_argument("--config", default="configs/panel-static-zone-baseline.json")
    args = parser.parse_args()

    config = load_panel_static_zone_config(args.config)
    result = run_panel_static_zone(config)
    write_panel_static_zone_outputs(config, result)
    print(json.dumps(_console_summary(result.summary, config.output_dir), indent=2))


def _console_summary(summary: dict[str, object], output_dir: Path) -> dict[str, object]:
    return {
        "output_dir": str(output_dir),
        "layout": summary["layout"],
        "zone_count": summary["zone_count"],
        "request_count": summary["request_count"],
        "drive_makespan_h": float(summary["drive_makespan_s"]) / 3600.0,
        "system_drain_h": float(summary["system_drain_s"]) / 3600.0,
        "throughput_req_per_s": summary["throughput_req_per_s"],
        "shuttle_utilization_avg": summary["shuttle_utilization_avg"],
        "reader_utilization_avg": summary["reader_utilization_avg"],
    }


if __name__ == "__main__":
    main()
