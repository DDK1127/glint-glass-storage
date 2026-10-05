"""Run the controlled eight-zone motivation matrix, independent of older pilots."""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import random
from statistics import mean, stdev
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from glass_sim.sharing_buffer_study import Model, Request, Simulator, workload


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def aggregate(rows):
    keys = ("pattern", "load_fraction", "mode", "group_size", "buffer_slots")
    groups = {}
    for row in rows:
        groups.setdefault(tuple(row[k] for k in keys), []).append(row)
    output = []
    for key, group in sorted(groups.items()):
        item = dict(zip(keys, key))
        item["runs"] = len(group)
        for metric, value in group[0].items():
            if metric in keys or metric in {"seed", "trace_sha256", "cpu_wall_s"} or not isinstance(value, (int, float)):
                continue
            values = [row[metric] for row in group]
            item[metric + "_mean"] = mean(values)
            item[metric + "_sd"] = stdev(values) if len(values) > 1 else 0.0
        output.append(item)
    return output


def plots(rows, output, example):
    os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "results/.mplconfig"))
    os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "results/.cache"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    modes = sorted({(r["mode"], r["group_size"]) for r in rows}, key=lambda k: ({"fixed": 0, "transport": 1, "joint": 2}[k[0]], k[1]))
    buffers = sorted({r["buffer_slots"] for r in rows})
    patterns = sorted({r["pattern"] for r in rows})
    loads = sorted({r["load_fraction"] for r in rows})
    labels = ["Fixed" if m == "fixed" else f"{'Transport' if m == 'transport' else 'Joint'}-{g}" for m, g in modes]
    fig, axes = plt.subplots(len(patterns), len(loads), figsize=(13, 8), squeeze=False)
    for pi, pattern in enumerate(patterns):
        for li, load in enumerate(loads):
            ax = axes[pi, li]
            matrix = [[next(r["latency_p99_s_mean"] / 60 for r in rows if (r["pattern"], r["load_fraction"], r["mode"], r["group_size"], r["buffer_slots"]) == (pattern, load, m, g, b)) for b in buffers] for m, g in modes]
            im = ax.imshow(matrix, cmap="YlOrRd", aspect="auto")
            for i in range(len(modes)):
                for j in range(len(buffers)):
                    ax.text(j, i, f"{matrix[i][j]:.1f}", ha="center", va="center", fontsize=9)
            ax.set_yticks(range(len(modes)), labels)
            ax.set_xticks(range(len(buffers)), buffers)
            ax.set_xlabel("Waiting slots per reader")
            ax.set_title(f"{pattern}; arrival rate = {load:g} x calibrated rate")
            fig.colorbar(im, ax=ax, label="Mean of run p99 (min)")
    fig.suptitle("Eight zones / eight shuttles / eight readers — controlled workload")
    fig.tight_layout()
    fig.savefig(output / "fig1_latency.png", dpi=170)
    plt.close(fig)

    pattern, load = "hotspot", max(loads)
    selected = [next(r for r in rows if (r["pattern"], r["load_fraction"], r["mode"], r["group_size"], r["buffer_slots"]) == (pattern, load, m, g, b)) for m, g in modes for b in buffers]
    fig, ax = plt.subplots(figsize=(14, 5))
    bottom = np.zeros(len(selected))
    for metric, label in [("dispatch_queue_mean_s", "Before dispatch"), ("fetch_delivery_mean_s", "Fetch + delivery (incl. traffic/pick)"), ("delivery_wait_mean_s", "Blocked handoff"), ("handoff_mean_s", "Handoff"), ("input_wait_mean_s", "Input staging"), ("reader_service_mean_s", "Load/mount/read")]:
        vals = np.array([r[metric + "_mean"] / 60 for r in selected])
        ax.bar(range(len(selected)), vals, bottom=bottom, label=label)
        bottom += vals
    ax.set_xticks(range(len(selected)), [f"{label}\nB={b}" for label in labels for b in buffers], rotation=40, ha="right")
    ax.set_ylabel("Mean request latency (min)")
    ax.set_title("Hotspot / higher load: request latency accounting (not a p99 decomposition)")
    ax.legend(fontsize=8, ncol=3)
    fig.tight_layout()
    fig.savefig(output / "fig2_latency_breakdown.png", dpi=170)
    plt.close(fig)

    metrics = [("movement_s", "Moving"), ("traffic_wait_s", "Waiting for reserved route"), ("delivery_wait_s", "Waiting to hand off"), ("idle_reader_with_demand_s", "Idle reader with outstanding demand")]
    fig, axes = plt.subplots(2, 2, figsize=(14, 8))
    for ax, (metric, label) in zip(axes.flat, metrics):
        ax.bar(range(len(selected)), [r[metric + "_mean"] / r["requests_mean"] for r in selected])
        ax.set_title(label)
        ax.set_ylabel("Resource-seconds / request")
        ax.set_xticks(range(len(selected)), [f"{name}\n{b}" for name in labels for b in buffers], rotation=60, ha="right", fontsize=7)
    fig.suptitle("Cause indicators overlap across resources; do not add them as latency")
    fig.tight_layout()
    fig.savefig(output / "fig3_resource_costs.png", dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(14, 7))
    resources = [f"shuttle_{i}" for i in range(8)] + [f"reader_{i}" for i in range(8)]
    horizon = 250.0
    colors = {"fetch": "#357ba3", "delivery": "#55a4bd", "return": "#80ab70", "to_output": "#a7c995", "traffic_wait": "#d99c35", "delivery_wait": "#b76660", "load_mount_read": "#6d6aaa", "output_block": "#a95787"}
    example, origin = example
    used = set()
    for row in example:
        start, end = max(0, row["start_s"] - origin), min(horizon, row["end_s"] - origin)
        if start >= horizon or end <= start:
            continue
        phase = row["phase"]
        ax.broken_barh([(start, end - start)], (resources.index(row["resource"]) - .35, .7), facecolors=colors.get(phase, "#999999"), label=phase if phase not in used else None)
        used.add(phase)
    ax.set_yticks(range(16), resources)
    ax.set_xlim(0, horizon)
    ax.set_xlabel("Seconds relative to the onset of the hotspot arrival episode")
    ax.set_title("Joint sharing, largest group, B=1; higher load — 250 s from hotspot onset")
    ax.legend(loc="upper left", bbox_to_anchor=(1, 1), fontsize=8)
    fig.tight_layout()
    fig.savefig(output / "fig4_timeline.png", dpi=170)
    plt.close(fig)


def write_report(aggregates, config, calibration, output):
    lines = ["# Eight-zone sharing / feeder-buffer motivation experiment", "", "## Scope", "",
             "這是新建的受控離散事件模型，未沿用舊研究的結果。8 zones / 8 shuttles / 8 readers；固定位置、硬體與交通規則。數字僅代表此模型與合成負載，不是已校準的 Silica 預測。", "",
             f"獨立 saturated fixed/B=0 校準：{calibration['requests']} requests，估計 finite-batch read drain rate {calibration['observed_read_throughput_req_s']:.6f} req/s。這不是穩態容量估計；所有方法共用同一 arrival rate。", "",
             "## Results", "", "數值是各 run 的 p99 的平均，並非 pooled p99。誤差與逐次結果見 aggregate.csv / runs.csv。", "",
             "| Pattern | Load factor | Mode | Group | Buffer slots | Mean p99 (s) | SD (s) | Delivery block / request (s) |",
             "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |"]
    for r in aggregates:
        lines.append(f"| {r['pattern']} | {r['load_fraction']:g} | {r['mode']} | {r['group_size']} | {r['buffer_slots']} | {r['latency_p99_s_mean']:.2f} | {r['latency_p99_s_sd']:.2f} | {r['delivery_wait_s_mean']/r['requests_mean']:.2f} |")
    lines += ["", "## Evidence boundary", "",
              "- Synthetic equal-size requests; one physical fetch/read/return per request. No online merge, cache, prefetch or future-arrival knowledge.",
              "- Middle-third hotspot puts 65% of requests in zones 3/4. Timing and local slot draws are paired with uniform workload; each method gets the identical trace within a case.",
              "- Local lanes and a single shared trunk are exclusive. Entire routes reserve all required resources for their duration. This conservative topology can dominate cross-zone sharing; results do not generalize to alternative rail networks.",
              "- Eight finite off-rail shuttle bays per zone are provisioned in every case (64 total). A bay accommodates the shuttle, including a carried platter; it is not a feeder slot. This generous fixed provision avoids unmodeled on-rail parking but is a hardware assumption.",
              "- Each reader has one finite output slot. A full output blocks unloading; returns have dispatch priority. No unlimited return staging.",
              "- Input capacity excludes the mounted platter and the output slot. B=0 uses direct handoff; a waiting shuttle remains occupied at a dock. The same local handoff mechanism and costs exist for every B.",
              "- Return service is charged and every platter goes home. Request completion excludes its own unload/return, which can delay later requests.",
              "- Transport sharing uses contiguous home groups. Joint sharing adds reader eligibility within the same group. Glass never moves between physically disconnected components.",
              "- Controller: returns first, then oldest currently feasible request; earliest estimated pickup shuttle; joint mode chooses estimated earliest completion reader including committed in-flight work. Finite-buffer release and output blockage are only approximately predicted, not optimized.",
              "- Excluded-work idle time is an upper-bound opportunity indicator, not proof that helping would improve completion. Demand-free reader idle is excluded from the starvation indicator.",
              "- Sharing groups 2/4/8 also change which hotspot zones can cooperate (zones 3/4 straddle the group boundary for 2/4). Group-size effects cannot be attributed solely to the number of eligible robots; balanced and shifted partitions are a follow-up sensitivity.",
              "- Fixed-duration mechanics and one finite workload episode: no real-trace generalization, no confidence claim from three seeds, no cost/energy claim or novel-algorithm claim.", "",
              "## Reproduce", "", "```bash", f".venv/bin/python scripts/run_sharing_buffer_study.py --config {config}", "```", "",
              "Audit CSVs retain requests, complete jobs, shuttle/reader timeline and transport reservations for the first seed of the hotspot higher-load cases. Figures are PNG; no PDF export required."]
    (output / "ANALYSIS_ZH.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "experiments/sharing-buffer/smoke.json")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    raw = json.loads(args.config.read_text())
    model = Model(**raw["model"])
    model.validate()
    if not raw["seeds"] or len(set(raw["seeds"])) != len(raw["seeds"]):
        raise ValueError("Unique nonempty seeds required")
    if not raw["load_fractions"] or any(not math.isfinite(x) or x <= 0 for x in raw["load_fractions"]):
        raise ValueError("Positive finite load fractions required")
    if not raw["group_sizes"] or any(g not in [2, 4, 8] for g in raw["group_sizes"]):
        raise ValueError("Sharing groups must be 2/4/8")
    output = args.output_dir or ROOT / raw["output_dir"]
    output.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    rng = random.Random(raw["calibration_seed"])
    calibration_trace = [Request(i, 0.0, (i % 8) * model.slots_per_zone + rng.randrange(model.slots_per_zone)) for i in range(raw["calibration_requests"])]
    calibration, _, _ = Simulator(model, calibration_trace, "fixed", 1, 0).run()
    modes = [("fixed", 1)] + [(m, g) for m in ["transport", "joint"] for g in raw["group_sizes"]]
    total = len(raw["seeds"]) * 2 * len(raw["load_fractions"]) * len(modes) * len(raw["buffer_slots"])
    print(f"Independent calibration rate: {calibration['observed_read_throughput_req_s']:.6f} req/s; {total} paired runs", flush=True)
    rows, example = [], []
    for seed in raw["seeds"]:
        for pattern in ["uniform", "hotspot"]:
            for load in raw["load_fractions"]:
                rate = load * calibration["observed_read_throughput_req_s"]
                trace = workload(model, raw["requests"], seed, rate, pattern)
                for mode, group in modes:
                    for capacity in raw["buffer_slots"]:
                        simulation = Simulator(model, trace, mode, group, capacity)
                        run_start = perf_counter()
                        summary, jobs, timeline = simulation.run()
                        rows.append(dict(seed=seed, pattern=pattern, load_fraction=load, arrival_rate_req_s=rate, **summary, cpu_wall_s=perf_counter() - run_start))
                        if seed == raw["seeds"][0] and pattern == "hotspot" and load == max(raw["load_fractions"]):
                            audit = output / f"audit-{mode}-{group}-b{capacity}"
                            audit.mkdir(exist_ok=True)
                            write_csv(audit / "requests.csv", [asdict(r) for r in trace])
                            write_csv(audit / "jobs.csv", jobs)
                            write_csv(audit / "timeline.csv", timeline)
                            write_csv(audit / "reservations.csv", simulation.transport.records)
                            if mode == "joint" and group == max(raw["group_sizes"]) and capacity == 1:
                                example = (timeline, trace[len(trace) // 3].arrival_s)
                    print(f"{len(rows)}/{total}: seed={seed} {pattern} load={load:g} {mode}/{group}", flush=True)
    aggregates = aggregate(rows)
    paired = {}
    for row in rows:
        key = (row["seed"], row["pattern"], row["load_fraction"])
        paired.setdefault(key, set()).add(row["trace_sha256"])
    if any(len(signatures) != 1 for signatures in paired.values()):
        raise RuntimeError("Trace pairing failed")
    write_csv(output / "runs.csv", rows)
    write_csv(output / "aggregate.csv", aggregates)
    source_files = [Path(__file__), ROOT / "glass_sim/sharing_buffer_study.py"]
    result = dict(config=raw, effective_model=asdict(model), calibration=calibration, run_count=len(rows),
                  source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files},
                  validation=dict(all_requests_read_and_returned=True, paired_traces=True, finite_input_output=True, exclusive_routes=True, exclusive_shuttles_readers=True, causal_service=True, mean_latency_accounting=True),
                  wall_s=perf_counter() - started)
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    write_report(aggregates, str(args.config.relative_to(ROOT)) if args.config.is_relative_to(ROOT) else str(args.config), calibration, output)
    plots(aggregates, output, example)
    print(f"Completed {len(rows)} runs in {perf_counter() - started:.1f}s; {output}", flush=True)


if __name__ == "__main__":
    main()
