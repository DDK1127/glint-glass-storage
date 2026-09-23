"""Two-shuttle passing example on an explicitly abstract, two-lane graph."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import csv
import json
import math
import os
from pathlib import Path

from .panel_static_zone import (
    PanelGeometryConfig, PanelMovementConfig, PanelTimingConfig,
    PanelWorkloadConfig, PanelStaticZoneConfig, PanelStaticZoneSimulator,
)


@dataclass(frozen=True)
class Event:
    shuttle: str
    kind: str
    start: float
    end: float
    source: str
    target: str

    @property
    def resources(self) -> set[str]:
        # Reserve endpoints throughout a move, conservatively preventing entry.
        resources = {self.source, self.target}
        if self.source != self.target:
            resources.add("edge:" + ":".join(sorted((self.source, self.target))))
        return resources


def travel_times(distance_m: float, speed: float, accel: float, crab_s: float) -> tuple[float, float]:
    if not all(math.isfinite(v) and v > 0 for v in (distance_m, speed, accel, crab_s)):
        raise ValueError("Distance, speed, acceleration and lane-change time must be positive and finite")
    config = PanelStaticZoneConfig(
        output_dir=Path("."), seed=0,
        geometry=PanelGeometryConfig(2, 1, distance_m, 2, 1),
        movement=PanelMovementConfig(speed, accel, 1.0, crab_s),
        timing=PanelTimingConfig(0, 0, 0, 0, 0, 0, 60),
        workload=PanelWorkloadConfig(1, 1),
    )
    simulator = PanelStaticZoneSimulator(config)
    return simulator._horizontal_time_s(distance_m), crab_s


def validate(events: list[Event], starts: dict[str, str], goals: dict[str, str]) -> None:
    horizon = max(e.end for e in events)
    occupancy = list(events)
    valid_edges = {frozenset(pair) for pair in (("L0", "R0"), ("L1", "R1"), ("L0", "L1"), ("R0", "R1"))}
    for shuttle, initial in starts.items():
        time, position = 0.0, initial
        own = sorted((e for e in events if e.shuttle == shuttle), key=lambda e: e.start)
        if not own:
            raise ValueError("Missing shuttle trajectory")
        for event in own:
            if not (math.isfinite(event.start) and math.isfinite(event.end) and event.end > event.start):
                raise ValueError("Invalid event interval")
            if not math.isclose(event.start, time, abs_tol=1e-9) or event.source != position:
                raise ValueError("Trajectory gap, overlap or teleport")
            if event.source != event.target and frozenset((event.source, event.target)) not in valid_edges:
                raise ValueError("Invalid graph edge")
            time, position = event.end, event.target
        if position != goals[shuttle]:
            raise ValueError("Goal not reached")
        if time < horizon:
            occupancy.append(Event(shuttle, "parked", time, horizon, position, position))
    if any(e.shuttle not in starts for e in events):
        raise ValueError("Unknown shuttle")
    for i, left in enumerate(occupancy):
        for right in occupancy[i + 1:]:
            overlap = min(left.end, right.end) - max(left.start, right.start)
            if left.shuttle != right.shuttle and overlap > 1e-9 and left.resources & right.resources:
                raise ValueError("Conflicting space-time reservations")


def build_demo(distance_m: float = 6, speed: float = 2, accel: float = 2, crab_s: float = 3) -> dict:
    horizontal, vertical = travel_times(distance_m, speed, accel, crab_s)
    reference = [
        Event("A", "horizontal", 0, horizontal, "L0", "R0"),
        Event("B", "horizontal", 0, horizontal, "R1", "L1"),
    ]
    # B clears the main lane before A is admitted. Separate lanes then run in parallel.
    passing = [
        Event("A", "waiting", 0, vertical, "L0", "L0"),
        Event("A", "horizontal", vertical, vertical + horizontal, "L0", "R0"),
        Event("B", "yield", 0, vertical, "R0", "R1"),
        Event("B", "horizontal", vertical, vertical + horizontal, "R1", "L1"),
        Event("B", "yield", vertical + horizontal, 2 * vertical + horizontal, "L1", "L0"),
    ]
    validate(reference, {"A": "L0", "B": "R1"}, {"A": "R0", "B": "L1"})
    validate(passing, {"A": "L0", "B": "R0"}, {"A": "R0", "B": "L0"})
    summaries = []
    for case, events in (("independent_lanes", reference), ("head_on_with_bypass", passing)):
        for shuttle in ("A", "B"):
            own = [e for e in events if e.shuttle == shuttle]
            sums = {kind: sum(e.end - e.start for e in own if e.kind == kind) for kind in ("waiting", "horizontal", "yield")}
            completion = max(e.end for e in own)
            if not math.isclose(completion, sum(sums.values())):
                raise ValueError("Time accounting failed")
            summaries.append(dict(case=case, shuttle=shuttle, completion_s=completion,
                                  horizontal_s=sums["horizontal"], waiting_s=sums["waiting"],
                                  lane_change_s=sums["yield"], added_time_s=completion-horizontal))
    return dict(
        config=dict(distance_m=distance_m, speed_m_s=speed, accel_m_s2=accel, lane_change_s=crab_s),
        events={"independent_lanes": reference, "head_on_with_bypass": passing},
        summary=summaries,
        validation=dict(passed=True, trajectory_continuity=True, reservation_conflicts=0, parked_occupancy_checked=True),
        scope="Abstract lanes with sufficient body clearance; not a calibrated Silica traffic model. No reader or platter handling. Independent lanes are a reference, not an identical-start baseline.",
    )


def write_outputs(result: dict, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    rows = [dict(case=case, **asdict(e)) for case, events in result["events"].items() for e in events]
    for name, data in (("events.csv", rows), ("summary.csv", result["summary"])):
        with (output / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(data[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(data)
    serializable = dict(result, events=rows)
    (output / "summary.json").write_text(json.dumps(serializable, indent=2) + "\n", encoding="utf-8")
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/glint-mplconfig")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    palette = {"horizontal": "#327ba4", "waiting": "#e5ac48", "yield": "#569769"}
    fig, axes = plt.subplots(2, 1, figsize=(10, 5.6), sharex=True)
    horizon = max(row["completion_s"] for row in result["summary"])
    for ax, (case, events), title in zip(axes, result["events"].items(),
            ("(a) Independent lanes: travel-time reference", "(b) Head-on encounter: B clears the lane, then both move")):
        for event in events:
            y = 1 if event.shuttle == "A" else 0
            width = event.end-event.start
            ax.broken_barh([(event.start, width)], (y-.23, .46), facecolors=palette[event.kind])
            label = {"waiting": "Wait", "horizontal": "Travel", "yield": "Change rack"}[event.kind]
            ax.text(event.start+width/2, y, f"{label}\n{width:g} s", ha="center", va="center", fontsize=10,
                    color="#182126" if event.kind == "waiting" else "white")
        for row in result["summary"]:
            if row["case"] == case:
                ax.text(row["completion_s"]+.12, 1 if row["shuttle"] == "A" else 0,
                        f"Done {row['completion_s']:g}s", va="center", fontsize=10)
        ax.set_yticks([1, 0], ["Shuttle A", "Shuttle B"])
        ax.set_ylim(-.6, 1.7)
        ax.set_xlim(0, horizon+1.6)
        ax.set_title(title, loc="left", fontsize=11)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.set_axisbelow(True)
        ax.grid(axis="x", alpha=.2)
    axes[-1].set_xlabel("Elapsed time (s)")
    fig.legend(handles=[Patch(color=palette[k], label=v) for k, v in
               (("horizontal", "Horizontal travel"), ("waiting", "Waiting"), ("yield", "Extra rack changes"))],
               loc="upper center", ncol=3, frameon=False)
    cfg = result["config"]
    fig.text(.5, .025, f"Assumed: {cfg['distance_m']:g} m rack path; {cfg['speed_m_s']:g} m/s; {cfg['accel_m_s2']:g} m/s^2; {cfg['lane_change_s']:g} s per rack change. Abstract collision-free reservations.",
             ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .07, 1, .92))
    for extension in ("png", "pdf"):
        fig.savefig(output / f"fig1_yield_timeline.{extension}", dpi=200)
    plt.close(fig)

    from matplotlib.patches import FancyArrowPatch

    passing = result["events"]["head_on_with_bypass"]
    fig, axes = plt.subplots(2, 1, figsize=(10, 5.6), gridspec_kw={"height_ratios": [1.05, 1.45]})
    spatial, timeline = axes
    distance = cfg["distance_m"]
    left_x, right_x, conflict_x = 0.12 * distance, 0.88 * distance, 0.5 * distance
    spatial.plot([0, distance], [1, 1], color="#7b858b", linewidth=4, solid_capstyle="round")
    spatial.plot([0, distance], [0, 0], color="#aeb7bc", linewidth=4, solid_capstyle="round")
    spatial.text(-.15, 1, "Rack 0", ha="right", va="center", fontsize=11, fontweight="bold")
    spatial.text(-.15, 0, "Rack 1", ha="right", va="center", fontsize=11, fontweight="bold")
    spatial.scatter([left_x, right_x], [1, 1], s=170, color=["#327ba4", "#e5ac48"], zorder=3)
    spatial.text(left_x, 1, "A", color="white", ha="center", va="center", fontsize=10, fontweight="bold")
    spatial.text(right_x, 1, "B", color="#182126", ha="center", va="center", fontsize=10, fontweight="bold")
    spatial.add_patch(FancyArrowPatch((0.18 * distance, 1), (0.45 * distance, 1), arrowstyle="-|>", mutation_scale=16, color="#327ba4", linewidth=2))
    spatial.add_patch(FancyArrowPatch((0.82 * distance, 1), (0.55 * distance, 1), arrowstyle="-|>", mutation_scale=16, color="#e5ac48", linewidth=2))
    spatial.scatter([conflict_x], [1], marker="x", s=110, color="#b95c55", linewidth=2.2, zorder=4)
    spatial.text(conflict_x, 1.25, "Head-on conflict", ha="center", va="bottom", fontsize=11, color="#b95c55", fontweight="bold")
    spatial.add_patch(FancyArrowPatch((right_x, .9), (right_x, .1), arrowstyle="-|>", mutation_scale=16, color="#569769", linewidth=2))
    spatial.add_patch(FancyArrowPatch((0.82 * distance, 0), (0.18 * distance, 0), arrowstyle="-|>", mutation_scale=16, color="#569769", linewidth=2))
    spatial.text(0.52 * distance, -.28, "B changes rack and bypasses A", ha="center", va="top", fontsize=11, color="#3f7649", fontweight="bold")
    spatial.set_xlim(-0.1 * distance, 1.05 * distance)
    spatial.set_ylim(-.65, 1.55)
    spatial.axis("off")
    spatial.set_title("Head-on encounter: spatial view", loc="left", fontsize=12)

    for event in passing:
        y = 1 if event.shuttle == "A" else 0
        width = event.end - event.start
        timeline.broken_barh([(event.start, width)], (y - .23, .46), facecolors=palette[event.kind])
        event_label = {"waiting": "Wait", "horizontal": "Travel", "yield": "Change rack"}[event.kind]
        timeline.text(event.start + width / 2, y, f"{event_label}\n{width:g} s", ha="center", va="center", fontsize=9,
                      color="#182126" if event.kind == "waiting" else "white")
    timeline.set_yticks([1, 0], ["Shuttle A", "Shuttle B"])
    timeline.set_ylim(-.6, 1.65)
    timeline.set_xlim(0, max(event.end for event in passing) + .5)
    timeline.set_xlabel("Elapsed time (s)")
    timeline.set_title("Conflict-free schedule: A waits while B changes rack", loc="left", fontsize=12)
    timeline.spines[["top", "right", "left"]].set_visible(False)
    timeline.grid(axis="x", alpha=.2)
    fig.tight_layout()
    for extension in ("png", "pdf"):
        fig.savefig(output / f"fig2_head_on_explainer.{extension}", dpi=200)
    plt.close(fig)
