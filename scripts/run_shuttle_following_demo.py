"""Run a configured same-direction catch-up example."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from glass_sim.shuttle_following_demo import FollowingConfig, run_following, write_outputs

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "experiments/shuttle-following-demo/default.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results/shuttle-following-demo")
    args = parser.parse_args()
    result = run_following(FollowingConfig(**json.loads(args.config.read_text())))
    write_outputs(result, args.output_dir)
    print(json.dumps(result["summary"], indent=2))
