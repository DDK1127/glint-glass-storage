from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = (
    Path.cwd().resolve()
    if (Path.cwd() / "experiments").is_dir()
    else PACKAGE_ROOT
)
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(REPOSITORY_ROOT / "results" / ".mplconfig"),
)
os.environ.setdefault(
    "XDG_CACHE_HOME",
    str(REPOSITORY_ROOT / "results" / ".cache"),
)

from .natural_trace_skew import (
    load_natural_trace_skew_config,
    run_natural_trace_skew_study,
    write_natural_trace_skew_outputs,
)
from .azure_blob_preprocess import (
    load_azure_blob_preprocess_config,
    preprocess_azure_blob_trace,
)
from .adaptive_zone_study import (
    load_adaptive_zone_study_config,
    run_adaptive_zone_study,
    write_adaptive_zone_outputs,
)
from .static_baseline_study import (
    load_static_baseline_study_config,
    run_static_baseline_study,
    write_static_baseline_study_outputs,
)
from .static_ownership_motivation import (
    load_static_ownership_motivation_config,
    run_static_ownership_motivation,
    write_static_ownership_motivation_outputs,
)
from .static_ownership_threshold import (
    load_static_ownership_threshold_config,
    run_static_ownership_threshold,
    write_static_ownership_threshold_outputs,
)
from .skew_threshold_study import (
    load_skew_threshold_config,
    run_skew_threshold_study,
    write_skew_threshold_outputs,
)
from .work_stealing_study import (
    load_work_stealing_study_config,
    run_work_stealing_study,
    write_work_stealing_study_outputs,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="glint-sim",
        description="Run current Glass static-zone research experiments.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_command(
        subparsers,
        "preprocess-azure-blob",
        "Create a stable, read-only canonical Azure Blob trace.",
        "azure-blob-preprocessing",
    )
    _add_command(
        subparsers,
        "rq1",
        "Characterize natural post-merge zone skew.",
        "rq1-natural-skew",
    )
    _add_command(
        subparsers,
        "static-baseline",
        "Characterize strict static-zone imbalance.",
        "static-baseline",
    )
    _add_command(
        subparsers,
        "skew-threshold",
        "Measure merged-workload throughput as request skew increases.",
        "rq2-skew-threshold",
    )
    _add_command(
        subparsers,
        "work-stealing",
        "Measure one-helper work-stealing tradeoffs.",
        "work-stealing",
    )
    _add_command(
        subparsers,
        "adaptive-zone-upper-bound",
        "Compare equal-size static zones with batch-oracle adaptive boundaries.",
        "adaptive-zone-upper-bound",
    )
    _add_command(
        subparsers,
        "static-ownership-motivation",
        "Isolate imbalance caused by non-overlapping static ownership.",
        "static-ownership-motivation",
    )
    _add_command(
        subparsers,
        "static-ownership-threshold",
        "Measure when owner concentration degrades static throughput.",
        "static-ownership-threshold",
    )
    args = parser.parse_args()

    if args.command == "preprocess-azure-blob":
        _run_azure_blob_preprocess(args.config)
    elif args.command == "rq1":
        _run_rq1(args.config)
    elif args.command == "static-baseline":
        _run_static_baseline(args.config)
    elif args.command == "skew-threshold":
        _run_skew_threshold(args.config)
    elif args.command == "work-stealing":
        _run_work_stealing(args.config)
    elif args.command == "adaptive-zone-upper-bound":
        _run_adaptive_zone(args.config)
    elif args.command == "static-ownership-motivation":
        _run_static_ownership_motivation(args.config)
    else:
        _run_static_ownership_threshold(args.config)


def _run_azure_blob_preprocess(config_path: str) -> None:
    config = load_azure_blob_preprocess_config(config_path)
    manifest = preprocess_azure_blob_trace(config)
    _print(
        {
            "output_path": str(config.output_path),
            "input_rows": manifest["source_stats"]["input_rows"],
            "read_rows": manifest["source_stats"]["read_rows"],
            "validation_passed": manifest["validation"]["passed"],
        }
    )


def _add_command(
    subparsers: argparse._SubParsersAction,
    name: str,
    help_text: str,
    experiment_dir: str,
) -> None:
    command = subparsers.add_parser(name, help=help_text)
    command.add_argument(
        "--config",
        default=str(REPOSITORY_ROOT / "experiments" / experiment_dir / "smoke.json"),
        help="Experiment JSON config. Defaults to the smoke configuration.",
    )


def _run_rq1(config_path: str) -> None:
    config = load_natural_trace_skew_config(config_path)
    study = run_natural_trace_skew_study(config)
    write_natural_trace_skew_outputs(config, study)
    _print(
        {
            "output_dir": str(config.output_dir),
            "read_requests": study.source_stats["read_requests"],
            "trace_span_minutes": study.source_stats["trace_span_s"] / 60.0,
            "validation_passed": study.validation["passed"],
        }
    )


def _run_static_baseline(config_path: str) -> None:
    config = load_static_baseline_study_config(config_path)
    study = run_static_baseline_study(config)
    write_static_baseline_study_outputs(config, study)
    _print(
        {
            "output_dir": str(config.output_dir),
            "runs": len(study.runs),
            "aggregate_rows": len(study.aggregate_rows),
        }
    )


def _run_skew_threshold(config_path: str) -> None:
    config = load_skew_threshold_config(config_path)
    result = run_skew_threshold_study(config)
    write_skew_threshold_outputs(config, result)
    _print(
        {
            "output_dir": str(config.output_dir),
            "runs": len(result.run_rows),
            "aggregate_rows": len(result.aggregate_rows),
            "validation_passed": result.validation["passed"],
        }
    )


def _run_work_stealing(config_path: str) -> None:
    config = load_work_stealing_study_config(config_path)
    study = run_work_stealing_study(config)
    write_work_stealing_study_outputs(config, study)
    _print(
        {
            "output_dir": str(config.output_dir),
            "static_runs": len(study.static_runs),
            "helper_runs": len(study.helper_runs),
            "aggregate_rows": len(study.aggregate_rows),
        }
    )


def _run_adaptive_zone(config_path: str) -> None:
    config = load_adaptive_zone_study_config(config_path)
    study = run_adaptive_zone_study(config)
    write_adaptive_zone_outputs(config, study)
    _print(
        {
            "output_dir": str(config.output_dir),
            "runs": len(study.run_rows),
            "aggregate_rows": len(study.aggregate_rows),
            "validation_passed": study.validation["passed"],
        }
    )


def _run_static_ownership_motivation(config_path: str) -> None:
    config = load_static_ownership_motivation_config(config_path)
    study = run_static_ownership_motivation(config)
    write_static_ownership_motivation_outputs(config, study)
    _print(
        {
            "output_dir": str(config.output_dir),
            "runs": len(study.run_rows),
            "aggregate_rows": len(study.aggregate_rows),
            "validation_passed": study.validation["passed"],
        }
    )


def _run_static_ownership_threshold(config_path: str) -> None:
    config = load_static_ownership_threshold_config(config_path)
    study = run_static_ownership_threshold(config)
    write_static_ownership_threshold_outputs(config, study)
    _print(
        {
            "output_dir": str(config.output_dir),
            "runs": len(study.run_rows),
            "aggregate_rows": len(study.aggregate_rows),
            "validation_passed": study.validation["passed"],
        }
    )


def _print(summary: dict[str, object]) -> None:
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
