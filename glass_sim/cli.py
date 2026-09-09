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
from .azure_blob_batch import (
    extract_azure_blob_batch,
    load_azure_blob_batch_config,
)
from .azure_static_zone_pilot import (
    load_azure_static_zone_pilot_config,
    run_azure_static_zone_pilot,
    write_azure_static_zone_pilot_outputs,
)
from .azure_capacity_scalability import (
    load_azure_capacity_scalability_config,
    run_azure_capacity_scalability,
    write_azure_capacity_scalability_outputs,
)
from .lun_address_static_zone import (
    load_lun_address_static_zone_config,
    run_lun_address_static_zone,
    write_lun_address_static_zone_outputs,
)
from .adaptive_zone_study import (
    load_adaptive_zone_study_config,
    run_adaptive_zone_study,
    write_adaptive_zone_outputs,
)
from .capacity_scalability import (
    load_capacity_scalability_config,
    run_capacity_scalability,
    write_capacity_scalability_outputs,
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
        "extract-azure-batch",
        "Extract one reproducible count-based Azure read batch.",
        "azure-blob-batch",
        "pilot.json",
    )
    _add_command(
        subparsers,
        "azure-static-zone-pilot",
        "Measure static ownership on the Azure head-100k batch.",
        "azure-static-zone-pilot",
    )
    _add_command(
        subparsers,
        "lun-address-static-zone",
        "Measure static-zone skew under fixed contiguous LUN address mapping.",
        "lun-address-static-zone",
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
    _add_command(
        subparsers,
        "capacity-scalability",
        "Measure fixed-resource performance as glass rack capacity grows.",
        "capacity-scalability",
    )
    _add_command(
        subparsers,
        "azure-capacity-scalability",
        "Run capacity scaling with Azure Blob request sizes and reuse.",
        "azure-capacity-scalability",
    )
    args = parser.parse_args()

    if args.command == "preprocess-azure-blob":
        _run_azure_blob_preprocess(args.config)
    elif args.command == "extract-azure-batch":
        _run_azure_blob_batch(args.config)
    elif args.command == "azure-static-zone-pilot":
        _run_azure_static_zone_pilot(args.config)
    elif args.command == "lun-address-static-zone":
        _run_lun_address_static_zone(args.config)
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
    elif args.command == "static-ownership-threshold":
        _run_static_ownership_threshold(args.config)
    elif args.command == "capacity-scalability":
        _run_capacity_scalability(args.config)
    else:
        _run_azure_capacity_scalability(args.config)


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


def _run_capacity_scalability(config_path: str) -> None:
    config = load_capacity_scalability_config(config_path)
    result = run_capacity_scalability(config)
    write_capacity_scalability_outputs(config, result)
    _print(
        {
            "output_dir": str(config.output_dir),
            "runs": len(result.run_rows),
            "aggregate_rows": len(result.aggregate_rows),
            "validation_passed": result.validation["passed"],
        }
    )


def _run_azure_capacity_scalability(config_path: str) -> None:
    config = load_azure_capacity_scalability_config(config_path)
    result = run_azure_capacity_scalability(config)
    write_azure_capacity_scalability_outputs(config, result)
    _print(
        {
            "output_dir": str(config.output_dir),
            "runs": len(result.run_rows),
            "aggregate_rows": len(result.aggregate_rows),
            "validation_passed": result.validation["passed"],
        }
    )


def _run_azure_blob_batch(config_path: str) -> None:
    config = load_azure_blob_batch_config(config_path)
    manifest = extract_azure_blob_batch(config)
    _print(
        {
            "output_path": str(config.output_path),
            "request_count": manifest["batch"]["request_count"],
            "span_s": manifest["batch"]["span_ms"] / 1000,
            "validation_passed": manifest["validation"]["passed"],
        }
    )


def _run_azure_static_zone_pilot(config_path: str) -> None:
    config = load_azure_static_zone_pilot_config(config_path)
    result = run_azure_static_zone_pilot(config)
    write_azure_static_zone_pilot_outputs(config, result)
    _print(
        {
            "output_dir": str(config.output_dir),
            "runs": len(result.run_rows),
            "validation_passed": result.validation["passed"],
        }
    )


def _run_lun_address_static_zone(config_path: str) -> None:
    config = load_lun_address_static_zone_config(config_path)
    result = run_lun_address_static_zone(config)
    write_lun_address_static_zone_outputs(config, result)
    _print(
        {
            "output_dir": str(config.output_dir),
            "logical_requests": result.summary["logical_request_count"],
            "physical_tasks": result.summary["physical_task_count"],
            "validation_passed": result.validation["passed"],
        }
    )


def _add_command(
    subparsers: argparse._SubParsersAction,
    name: str,
    help_text: str,
    experiment_dir: str,
    default_config_name: str = "smoke.json",
) -> None:
    command = subparsers.add_parser(name, help=help_text)
    command.add_argument(
        "--config",
        default=str(
            REPOSITORY_ROOT
            / "experiments"
            / experiment_dir
            / default_config_name
        ),
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
