"""A deterministic pickup-to-reader example, including acceleration and stopping."""
import csv
import json
import math
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/glint-mplconfig")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/shuttle-following-service"


def trajectory(start_x, phases):
    t, x, v = 0.0, start_x, 0.0
    segments = []
    for duration, acceleration in phases:
        segments.append((t, t + duration, x, v, acceleration))
        x += v * duration + acceleration * duration**2 / 2
        v += acceleration * duration
        t += duration
    assert math.isclose(v, 0, abs_tol=1e-9)
    return segments, x, t


def state(segments, t):
    for start, end, x, v, a in segments:
        if t <= end + 1e-9:
            dt = t-start
            return x+v*dt+a*dt**2/2, v+a*dt, a
    start, end, x, v, a = segments[-1]
    dt = end-start
    return x+v*dt+a*dt**2/2, 0.0, 0.0


def main():
    # A and B finish pickup together, start from rest and use different readers.
    a, ax, at = trajectory(4, [(1, 1), (7, 0), (1, -1)])
    b, bx, bt = trajectory(0, [(2, 1), (1, 0), (1, -1), (4, 0), (1, -1)])
    alone, end_x, free_t = trajectory(0, [(2, 1), (3, 0), (2, -1)])
    assert (ax, bx, end_x, at, bt, free_t) == (12, 10, 10, 9, 9, 7)
    boundaries = sorted({0.0, at} | {s[1] for s in a+b})
    candidates = set(boundaries)
    for left, right in zip(boundaries, boundaries[1:]):
        _, va, aa = state(a, (left+right)/2)
        _, vb, ab = state(b, (left+right)/2)
        if abs(aa-ab) > 1e-9:
            root = (left+right)/2 - (va-vb)/(aa-ab)
            if left < root < right:
                candidates.add(root)
    minimum_gap = min(state(a, t)[0]-state(b, t)[0] for t in candidates)
    assert minimum_gap >= 2-1e-9
    # All movement segments have positive velocity internally: no stopped wait.
    assert all(state(b, (s[0]+s[1])/2)[1] > 0 for s in b)
    pick, load = 3.0, 3.0
    total, baseline = pick+bt+load, pick+free_t+load
    summary = dict(pick_s=pick, reader_load_s=load, free_movement_s=free_t,
                   following_movement_s=bt, free_service_s=baseline,
                   following_service_s=total, stopped_waiting_s=0,
                   slowdown_penalty_s=total-baseline,
                   baseline_work_share=baseline/total, slowdown_penalty_share=(total-baseline)/total,
                   minimum_center_gap_m=minimum_gap,
                   assumptions="A max 1m/s, B max 2m/s; acceleration/deceleration magnitude 1m/s^2; initial center gap 4m; minimum center gap 2m. A reader at x12, B reader at x10. Both start pickup at t0, move from rest at t3. Separate readers, zero reader queue; finish after reader loading, before data read. Scripted policy, not optimal or production calibrated.",
                   validation="Continuous-time gap extrema checked; endpoints stopped; accounting conserved")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    events = [dict(case=case, phase=phase, start_s=start, end_s=end)
              for case, move in (("B alone", free_t), ("B following A", bt))
              for phase, start, end in (("Pickup", 0, pick), ("Movement", pick, pick+move), ("Reader load", pick+move, pick+move+load))]
    with (OUT / "events.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(events[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(events)
    details = [("Accelerate", 3, 5, "#367ca4"), ("Cruise", 5, 6, "#367ca4"),
               ("Slow down", 6, 7, "#c58d35"), ("Follow A", 7, 11, "#c58d35"),
               ("Stop at reader", 11, 12, "#367ca4")]
    with (OUT / "movement_events.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["phase", "start_s", "end_s"])
        writer.writerows((label, start, end) for label, start, end, _ in details)
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), gridspec_kw={"height_ratios": [1, 1.8, .9]})
    top, timeline, detail = axes
    top.set_xlim(-1, 14)
    top.set_ylim(-1.2, 1.5)
    top.axis("off")
    top.plot([0, 12], [0, 0], color="#afb8bf", linewidth=3)
    for x, label, color in ((0, "B: up to 2 m/s", "#367ca4"), (4, "A: up to 1 m/s", "#60986b")):
        top.add_patch(Rectangle((x-.25, -.15), .5, .3, color=color))
        top.annotate("", (x+1, .35), (x, .35), arrowprops=dict(arrowstyle="->", color=color, lw=2))
        top.text(x, .65, label, ha="center", fontsize=11)
    for x, label in ((10, "Reader for B"), (12, "Reader for A")):
        top.plot(x, 0, marker="s", color="#545e67", markersize=11)
        top.text(x, -.45, label, ha="center", fontsize=10)
    top.text(2, -.5, "Initial center gap: 4 m", ha="center", fontsize=10)
    top.set_title("Same direction: B catches up and slows down behind A", loc="left", fontsize=13)
    colors = {"Pickup": "#7e8791", "Movement": "#367ca4", "Reader load": "#60986b"}
    for e in events:
        y = 1 if e["case"] == "B alone" else 0
        duration = e["end_s"]-e["start_s"]
        timeline.broken_barh([(e["start_s"], duration)], (y-.23, .46), facecolors=colors[e["phase"]])
        label = "Move + slow following" if y == 0 and e["phase"] == "Movement" else e["phase"]
        timeline.text((e["start_s"]+e["end_s"])/2, y, f"{label}\n{duration:g} s", ha="center", va="center", color="white", fontsize=11)
    timeline.axvline(baseline, color="#ce8d30", linestyle="--", ymax=.82)
    timeline.annotate("", (15, -.55), (13, -.55), arrowprops=dict(arrowstyle="<->", color="#ae6f18", lw=2))
    timeline.text(14, -.66, "+2 s from slower travel\nStopped waiting: 0 s", ha="center", va="top", fontsize=10, color="#8c5917")
    timeline.set_yticks([1, 0], ["B alone\n13 s total", "B following A\n15 s total"])
    timeline.set_xticks([0, 3, 6, 9, 10, 12, 13, 15])
    timeline.set_xlim(0, 16)
    timeline.set_ylim(-1.15, 1.65)
    timeline.set_xlabel("Service elapsed time (s)")
    timeline.spines[["top", "right", "left"]].set_visible(False)
    timeline.set_axisbelow(True)
    timeline.grid(axis="x", alpha=.15)
    timeline.set_title("Pickup to reader loading; optical reading is outside this timeline", loc="left", fontsize=11)
    for label, start, end, color in details:
        detail.broken_barh([(start, end-start)], (0, .5), facecolors=color, edgecolors="white")
        label = label.replace(" ", "\n") if end-start <= 1 else label
        detail.text((start+end)/2, .25, f"{label}\n{end-start:g} s", ha="center", va="center", color="white", fontsize=9)
    detail.set_xlim(3, 12)
    detail.set_ylim(-.15, .85)
    detail.set_yticks([])
    detail.set_xticks([3, 5, 6, 7, 11, 12])
    detail.set_xlabel("Service elapsed time (s); enlarged movement interval")
    detail.spines[["top", "right", "left"]].set_visible(False)
    detail.set_title("B movement details: orange = affected by A; blue = normal acceleration / cruising / stopping", loc="left", fontsize=10)
    fig.text(.5, .03, "Cost accounting: baseline work 13/15 = 86.7%; slowdown penalty 2/15 = 13.3%; stopped waiting = 0%.\nIllustrative motion model with separate available readers; slowdown penalty is a time difference, not an idle interval.", ha="center", fontsize=10)
    fig.tight_layout(rect=(0, .11, 1, 1))
    for suffix in ("png", "pdf"):
        fig.savefig(OUT / f"fig1_pickup_to_reader.{suffix}", dpi=200)
    plt.close(fig)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
