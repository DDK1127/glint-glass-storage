from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from glass_sim.zone_nozone_comparison import load_config, run_comparison


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare strict static zoning with coordinated no-zone dispatch."
    )
    parser.add_argument(
        "--config",
        default=ROOT / "experiments/zone-nozone-comparison/full.json",
        type=Path,
    )
    args = parser.parse_args()
    result = run_comparison(load_config(args.config))
    print(json.dumps(result["aggregate"], indent=2))


if __name__ == "__main__":
    main()
