from __future__ import annotations

import argparse
import json
import sys

from .config import load_config, with_overrides
from .single_reader_scaling import load_scaling_config, run_scaling_experiment, write_scaling_outputs
from .simulator import GlassV2Simulator
from .panel_static_zone import (
    load_panel_static_zone_config,
    run_panel_static_zone,
    write_panel_static_zone_outputs,
)
from .static_zone import load_static_zone_config, run_static_zone_experiment, write_static_zone_outputs
from .static_baseline_study import (
    load_static_baseline_study_config,
    run_static_baseline_study,
    write_static_baseline_study_outputs,
)
from .workload_suite import (
    load_workload_suite_config,
    run_workload_suite,
    write_workload_suite_outputs,
)
from .trace_temporal_skew import (
    load_trace_temporal_skew_config,
    run_trace_temporal_skew_study,
    write_trace_temporal_skew_outputs,
)
from .trace_batch_skew import (
    load_trace_batch_skew_config,
    run_trace_batch_skew_study,
    write_trace_batch_skew_outputs,
)
from .trace import iter_trace


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "scaling":
        _run_scaling(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "static-zone":
        _run_static_zone(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "panel-static-zone":
        _run_panel_static_zone(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "static-baseline-study":
        _run_static_baseline_study(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "workload-suite":
        _run_workload_suite(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "trace-temporal-skew":
        _run_trace_temporal_skew(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "trace-batch-skew":
        _run_trace_batch_skew(sys.argv[2:])
        return

    parser = argparse.ArgumentParser(description="Run the Glass v2 simulator.")
    parser.add_argument("--config", default="configs/v2-smoke.json", help="Path to JSON config.")
    parser.add_argument("--trace", help="Override trace CSV path.")
    parser.add_argument("--output-dir", help="Override output directory.")
    parser.add_argument("--max-requests", type=int, help="Override max request count.")
    args = parser.parse_args()

    config = with_overrides(
        load_config(args.config),
        trace_path=args.trace,
        output_dir=args.output_dir,
        max_requests=args.max_requests,
    )
    simulator = GlassV2Simulator(config)
    result = simulator.run(iter_trace(config.trace_path, config.max_requests))
    simulator.write_outputs(result)
    print(json.dumps(_console_summary(result.summary), indent=2))


def _run_scaling(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Run single-reader N-shuttle scaling.")
    parser.add_argument("--config", default="configs/single-reader-scaling.json", help="Path to scaling JSON config.")
    args = parser.parse_args(argv)

    config = load_scaling_config(args.config)
    results = run_scaling_experiment(config)
    write_scaling_outputs(config, results)
    print(json.dumps(_scaling_console_summary(results, config.output_dir), indent=2))


def _run_static_zone(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Run static-zone v1 experiment.")
    parser.add_argument("--config", default="configs/static-zone-v1.json", help="Path to static-zone JSON config.")
    args = parser.parse_args(argv)

    config = load_static_zone_config(args.config)
    results = run_static_zone_experiment(config)
    write_static_zone_outputs(config, results)
    print(json.dumps(_static_zone_console_summary(results, config.output_dir), indent=2))


def _run_panel_static_zone(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Run panel static-zone direct-service baseline.")
    parser.add_argument("--config", default="configs/panel-static-zone-baseline.json")
    args = parser.parse_args(argv)

    config = load_panel_static_zone_config(args.config)
    result = run_panel_static_zone(config)
    write_panel_static_zone_outputs(config, result)
    print(json.dumps(_panel_static_zone_console_summary(result.summary, config.output_dir), indent=2))


def _run_static_baseline_study(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Characterize the strict panel static-zone baseline.")
    parser.add_argument("--config", default="configs/static-baseline-study.json")
    args = parser.parse_args(argv)

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


def _run_workload_suite(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Characterize synthetic workloads on the static-zone baseline.")
    parser.add_argument("--config", default="configs/static-zone-workload-suite.json")
    args = parser.parse_args(argv)

    config = load_workload_suite_config(args.config)
    suite = run_workload_suite(config)
    write_workload_suite_outputs(config, suite)
    print(
        json.dumps(
            {
                "output_dir": str(config.output_dir),
                "runs": len(suite.runs),
                "workload_cases": len(suite.aggregate_rows),
            },
            indent=2,
        )
    )


def _run_trace_temporal_skew(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Run trace-order temporal skew on strict static zones.")
    parser.add_argument("--config", default="configs/trace-temporal-skew-static.json")
    args = parser.parse_args(argv)

    config = load_trace_temporal_skew_config(args.config)
    study = run_trace_temporal_skew_study(config)
    write_trace_temporal_skew_outputs(config, study)
    print(
        json.dumps(
            {
                "output_dir": str(config.output_dir),
                "trace_requests": study.source_stats["trace_rows"],
                "atomic_tasks": study.source_stats["atomic_glass_tasks"],
                "workloads": len(study.runs),
            },
            indent=2,
        )
    )


def _run_trace_batch_skew(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Run consecutive trace-derived batches on strict static zones.")
    parser.add_argument("--config", default="configs/trace-batch-skew-static.json")
    args = parser.parse_args(argv)

    config = load_trace_batch_skew_config(args.config)
    study = run_trace_batch_skew_study(config)
    write_trace_batch_skew_outputs(config, study)
    print(
        json.dumps(
            {
                "output_dir": str(config.output_dir),
                "trace_requests": study.source_stats["trace_rows"],
                "batch_count": study.source_stats["batch_count"],
                "batch_size": study.source_stats["batch_size"],
                "workloads": len(study.runs),
            },
            indent=2,
        )
    )


def _panel_static_zone_console_summary(summary, output_dir) -> dict[str, object]:
    return {
        "output_dir": str(output_dir),
        "layout": summary["layout"],
        "zone_count": summary["zone_count"],
        "request_count": summary["request_count"],
        "drive_makespan_h": summary["drive_makespan_s"] / 3600.0,
        "system_drain_h": summary["system_drain_s"] / 3600.0,
        "throughput_req_per_s": summary["throughput_req_per_s"],
        "shuttle_utilization_avg": summary["shuttle_utilization_avg"],
        "reader_utilization_avg": summary["reader_utilization_avg"],
    }


def _static_zone_console_summary(results, output_dir) -> dict[str, object]:
    best = max(results, key=lambda row: row.summary["throughput_req_per_s"]) if results else None
    return {
        "runs": len(results),
        "output_dir": str(output_dir),
        "best_policy": best.policy if best else None,
        "best_skew_case": best.skew_case if best else None,
        "best_zone_count": best.zone_count if best else None,
        "best_throughput_req_per_s": best.summary["throughput_req_per_s"] if best else 0.0,
    }


def _scaling_console_summary(results, output_dir) -> dict[str, object]:
    saturation = next((row for row in results if row.summary.get("saturation_flag")), None)
    best = max(results, key=lambda row: row.summary["throughput_req_per_s"]) if results else None
    summary = {
        "runs": len(results),
        "output_dir": str(output_dir),
        "best_batch_size": best.summary.get("batch_size") if best else None,
        "best_shuttle_count": best.shuttle_count if best else None,
        "best_throughput_req_per_s": best.summary["throughput_req_per_s"] if best else 0.0,
        "saturation_batch_size": saturation.summary.get("batch_size") if saturation else None,
        "saturation_shuttle_count": saturation.shuttle_count if saturation else None,
    }
    return summary


def _console_summary(summary: dict[str, object]) -> dict[str, object]:
    return {
        "request_count": summary["request_count"],
        "makespan_s": summary["makespan_s"],
        "throughput_req_per_s": summary["throughput_req_per_s"],
        "cache_hit_rate": summary["cache_hit_rate"],
        "latency_s": summary["latency_s"],
        "output_dir": summary["config"]["output_dir"],  # type: ignore[index]
    }


if __name__ == "__main__":
    main()
