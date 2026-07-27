from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from glass_sim.azure_blob_preprocess import (
    load_azure_blob_preprocess_config,
    preprocess_azure_blob_trace,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a stable, read-only canonical Azure Blob trace."
    )
    parser.add_argument(
        "--config",
        default="experiments/azure-blob-preprocessing/full.json",
    )
    args = parser.parse_args()

    config = load_azure_blob_preprocess_config(args.config)
    manifest = preprocess_azure_blob_trace(config)
    print(
        json.dumps(
            {
                "output_path": str(config.output_path),
                "input_rows": manifest["source_stats"]["input_rows"],
                "read_rows": manifest["source_stats"]["read_rows"],
                "validation_passed": manifest["validation"]["passed"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
