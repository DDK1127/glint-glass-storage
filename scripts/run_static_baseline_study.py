from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("MPLCONFIGDIR", str(Path("results/.mplconfig").resolve()))
os.environ.setdefault("XDG_CACHE_HOME", str(Path("results/.cache").resolve()))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from glass_sim.static_baseline_study import (
    load_static_baseline_study_config,
    run_static_baseline_study,
    write_static_baseline_study_outputs,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Characterize the strict panel static-zone baseline.")
    parser.add_argument("--config", default="experiments/static-baseline/full.json")
    args = parser.parse_args()

    config = load_static_baseline_study_config(args.config)
    study = run_static_baseline_study(config)
    write_static_baseline_study_outputs(config, study)
    print(
        json.dumps(
            {
                "output_dir": str(config.output_dir),
                "runs": len(study.runs),
                "aggregate_rows": len(study.aggregate_rows),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
