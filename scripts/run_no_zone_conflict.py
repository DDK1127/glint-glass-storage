import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from glass_sim.no_zone_conflict import run_study

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Azure no-zone nearest-idle dispatch and conflict-exposure estimate")
    parser.add_argument("--config", type=Path, default=ROOT / "experiments/no-zone-conflict/full.json")
    args = parser.parse_args()
    print(json.dumps(run_study(json.loads(args.config.read_text()), ROOT)["aggregate"], indent=2))
