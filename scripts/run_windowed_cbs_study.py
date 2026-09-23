from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from glass_sim.windowed_cbs_study import load_study_config, run


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare Static, Greedy No-Zone, and small-window CBS."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "experiments/windowed-cbs/smoke.json",
    )
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    result = run(load_study_config(args.config), workers=args.workers)
    print(json.dumps(result["aggregate"], indent=2))


if __name__ == "__main__":
    main()
