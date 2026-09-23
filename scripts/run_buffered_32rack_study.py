from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from glass_sim.buffered_32rack_study import load_study_config, run


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the fixed 32-rack feeder-buffer study.")
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "experiments/buffered-32rack/smoke.json",
    )
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    run(load_study_config(args.config), workers=args.workers)


if __name__ == "__main__":
    main()
