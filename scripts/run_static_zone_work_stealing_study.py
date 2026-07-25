from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("MPLCONFIGDIR", str(Path("results/.mplconfig").resolve()))
os.environ.setdefault("XDG_CACHE_HOME", str(Path("results/.cache").resolve()))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from glass_sim.work_stealing_study import (
    load_work_stealing_study_config,
    run_work_stealing_study,
    write_work_stealing_study_outputs,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure static-zone hotspot imbalance and one-helper work stealing."
    )
    parser.add_argument(
        "--config",
        default="experiments/work-stealing/full.json",
    )
    args = parser.parse_args()

    config = load_work_stealing_study_config(args.config)
    study = run_work_stealing_study(config)
    write_work_stealing_study_outputs(config, study)
    print(
        json.dumps(
            {
                "output_dir": str(config.output_dir),
                "static_runs": len(study.static_runs),
                "helper_runs": len(study.helper_runs),
                "aggregate_rows": len(study.aggregate_rows),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
