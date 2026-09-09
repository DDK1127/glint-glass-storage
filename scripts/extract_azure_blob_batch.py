from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from glass_sim.azure_blob_batch import (
    extract_azure_blob_batch,
    load_azure_blob_batch_config,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract a reproducible request-count batch from the canonical Azure trace."
    )
    parser.add_argument(
        "--config",
        default="experiments/azure-blob-batch/pilot.json",
    )
    args = parser.parse_args()

    config = load_azure_blob_batch_config(args.config)
    manifest = extract_azure_blob_batch(config)
    print(
        json.dumps(
            {
                "output_path": str(config.output_path),
                "request_count": manifest["batch"]["request_count"],
                "span_s": manifest["batch"]["span_ms"] / 1000,
                "validation_passed": manifest["validation"]["passed"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
