from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("MPLCONFIGDIR", str(Path("outputs/.mplconfig").resolve()))
os.environ.setdefault("XDG_CACHE_HOME", str(Path("outputs/.cache").resolve()))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from glass_v2.static_zone import load_static_zone_config, run_static_zone_experiment, write_static_zone_outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the static-zone v1 experiment.")
    parser.add_argument("--config", default="configs/static-zone-v1.json", help="Path to static-zone JSON config.")
    args = parser.parse_args()

    config = load_static_zone_config(args.config)
    results = run_static_zone_experiment(config)
    write_static_zone_outputs(config, results)
    print(json.dumps(_console_summary(results, config.output_dir), indent=2))


def _console_summary(results, output_dir: Path) -> dict[str, object]:
    best = max(results, key=lambda row: row.summary["throughput_req_per_s"]) if results else None
    heavy_static = next(
        (
            row
            for row in results
            if row.policy == "static_zone" and row.skew_case == "heavy_skew" and row.zone_count == 4
        ),
        None,
    )
    heavy_shared = next(
        (
            row
            for row in results
            if row.policy == "shared_pool" and row.skew_case == "heavy_skew" and row.zone_count == 4
        ),
        None,
    )
    speedup = None
    if heavy_static and heavy_shared and heavy_static.summary["throughput_req_per_s"]:
        speedup = heavy_shared.summary["throughput_req_per_s"] / heavy_static.summary["throughput_req_per_s"]
    return {
        "runs": len(results),
        "output_dir": str(output_dir),
        "best_policy": best.policy if best else None,
        "best_skew_case": best.skew_case if best else None,
        "best_zone_count": best.zone_count if best else None,
        "best_throughput_req_per_s": best.summary["throughput_req_per_s"] if best else 0.0,
        "heavy_skew_4zone_shared_speedup": speedup,
    }


if __name__ == "__main__":
    main()
