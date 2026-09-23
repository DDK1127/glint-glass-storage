"""Run the small, deterministic passing experiment."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from glass_sim.shuttle_yield_demo import build_demo, write_outputs

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distance-m", type=float, default=6)
    parser.add_argument("--lane-change-s", type=float, default=3)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results/shuttle-yield-demo")
    args = parser.parse_args()
    result = build_demo(distance_m=args.distance_m, crab_s=args.lane_change_s)
    write_outputs(result, args.output_dir)
    print(json.dumps(result["summary"], indent=2))
