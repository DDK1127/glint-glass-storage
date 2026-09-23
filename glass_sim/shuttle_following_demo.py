"""Analytical same-direction following; a constant-speed leader is assumed."""
from dataclasses import asdict, dataclass
import csv
import json
import math
import os
from pathlib import Path


@dataclass(frozen=True)
class FollowingConfig:
    leader_speed_m_s: float = 1.0
    follower_speed_m_s: float = 2.0
    initial_center_gap_m: float = 4.0
    minimum_center_gap_m: float = 2.0
    braking_m_s2: float = 1.0
    checkpoint_m: float = 10.0
    sample_interval_s: float = 0.02

    def validate(self):
        if not all(math.isfinite(v) and v > 0 for v in asdict(self).values()):
            raise ValueError("All parameters must be positive and finite")
        relative_speed = self.follower_speed_m_s - self.leader_speed_m_s
        if relative_speed <= 0:
            raise ValueError("This catch-up scenario requires a faster follower")
        braking_closure = relative_speed**2 / (2 * self.braking_m_s2)
        if self.initial_center_gap_m < self.minimum_center_gap_m + braking_closure:
            raise ValueError("Insufficient gap for the assumed braking capability")


def run_following(config: FollowingConfig) -> dict:
    config.validate()
    lead, fast = config.leader_speed_m_s, config.follower_speed_m_s
    delta = fast - lead
    closure = delta**2 / (2 * config.braking_m_s2)
    brake_start = (config.initial_center_gap_m - config.minimum_center_gap_m - closure) / delta
    brake_duration = delta / config.braking_m_s2
    brake_end = brake_start + brake_duration
    x_start = fast * brake_start
    x_end = x_start + (fast + lead) * brake_duration / 2

    def follower_position(t):
        if t <= brake_start:
            return fast * t, fast
        if t <= brake_end:
            dt = t - brake_start
            return (x_start + fast * dt - config.braking_m_s2 * dt**2 / 2,
                    fast - config.braking_m_s2 * dt)
        return x_end + lead * (t - brake_end), lead

    target = config.checkpoint_m
    if target <= x_start:
        finish = target / fast
    elif target <= x_end:
        dt = 2 * (target - x_start) / (fast + math.sqrt(fast**2 - 2 * config.braking_m_s2 * (target - x_start)))
        finish = brake_start + dt
    else:
        finish = brake_end + (target - x_end) / lead
    horizon = max(finish, brake_end)
    count = math.ceil(horizon / config.sample_interval_s)
    times = sorted({min(i * config.sample_interval_s, horizon) for i in range(count + 1)} | {brake_start, brake_end, finish})
    samples = []
    for t in times:
        x, speed = follower_position(t)
        front = config.initial_center_gap_m + lead * t
        samples.append(dict(time_s=t, leader_x_m=front, follower_x_m=x,
                            follower_speed_m_s=speed, center_gap_m=front-x,
                            uncontrolled_follower_x_m=fast*t))
    # Gap decreases until speeds match, then is constant; its minimum is at brake_end.
    analytic_gap = config.initial_center_gap_m + lead * brake_end - x_end
    if analytic_gap < config.minimum_center_gap_m - 1e-9:
        raise ValueError("Unsafe analytical minimum gap")
    if not math.isclose(follower_position(finish)[0], target, abs_tol=1e-9):
        raise ValueError("Checkpoint crossing mismatch")
    phases = []
    for name, start, end in (("Cruise", 0, brake_start), ("Brake", brake_start, brake_end), ("Follow", brake_end, finish)):
        end = min(end, finish)
        if end > start:
            phases.append(dict(phase=name, start_s=start, end_s=end, duration_s=end-start))
    return dict(config=asdict(config), samples=samples, phases=phases,
                summary=dict(brake_start_s=brake_start, brake_end_s=brake_end,
                             braking_trigger_gap_m=config.minimum_center_gap_m+closure,
                             minimum_center_gap_m=analytic_gap,
                             uncontrolled_safe_gap_crossing_s=(config.initial_center_gap_m-config.minimum_center_gap_m)/delta,
                             uncontrolled_center_overlap_s=config.initial_center_gap_m/delta,
                             follower_checkpoint_s=finish, unobstructed_checkpoint_s=target/fast,
                             added_checkpoint_time_s=finish-target/fast,
                             leader_checkpoint_s=max(0, (target-config.initial_center_gap_m)/lead),
                             stopped_waiting_s=0),
                validation=dict(passed=True, continuous_time_gap_verified=True),
                scope="Already moving shuttles; constant-speed leader; exact state and immediate control. Minimum center gap includes assumed body clearance. No emergency leader braking, junctions, reader service, or terminal parking; checkpoint is crossed at speed.")


def write_outputs(result: dict, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    for name, rows in (("trajectory.csv", result["samples"]), ("events.csv", result["phases"]), ("summary.csv", [result["summary"]])):
        with (output / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/glint-mplconfig")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True, gridspec_kw={"height_ratios": [2, 1.5, 1]})
    samples, summary, config = result["samples"], result["summary"], result["config"]
    t = [r["time_s"] for r in samples]
    for field, label, color, style in (("leader_x_m", "A: leader", "#327ba4", "-"),
                                      ("follower_x_m", "B: controlled follower", "#569769", "-"),
                                      ("uncontrolled_follower_x_m", "B: no control (unsafe reference)", "#bb5a50", "--")):
        axes[0].plot(t, [r[field] for r in samples], color=color, linestyle=style, label=label, linewidth=2)
    axes[0].axhline(config["checkpoint_m"], color="#8b9299", linestyle=":", label="Checkpoint")
    axes[0].set_ylabel("Position (m)")
    axes[0].set_title("(a) A faster follower slows down before reaching the leader", loc="left", fontsize=11)
    axes[0].legend(frameon=False, fontsize=9)
    axes[1].plot(t, [r["center_gap_m"] for r in samples], color="#569769", linewidth=2)
    axes[1].axhline(config["minimum_center_gap_m"], color="#bb5a50", linestyle="--", label="Minimum center gap")
    axes[1].set_ylabel("Center gap (m)")
    axes[1].set_ylim(0, config["initial_center_gap_m"]+.5)
    axes[1].legend(frameon=False, fontsize=9)
    axes[1].set_title("(b) Safety is maintained throughout braking", loc="left", fontsize=11)
    colors = {"Cruise": "#327ba4", "Brake": "#d29c39", "Follow": "#569769"}
    for p in result["phases"]:
        axes[2].broken_barh([(p["start_s"], p["duration_s"])], (0, .6), facecolors=colors[p["phase"]])
        axes[2].text((p["start_s"]+p["end_s"])/2, .3, f"{p['phase']}\n{p['duration_s']:g}s", ha="center", va="center", color="white", fontsize=9)
    axes[2].set_yticks([.3], ["Shuttle B"])
    axes[2].set_ylim(-.15, .9)
    axes[2].set_xlabel("Elapsed time (s)")
    axes[2].set_title(f"(c) B reaches {config['checkpoint_m']:g} m at {summary['follower_checkpoint_s']:g}s; alone: {summary['unobstructed_checkpoint_s']:g}s. No stopped waiting.", loc="left", fontsize=11)
    for ax in axes:
        ax.axvline(summary["brake_start_s"], color="#999999", linestyle=":", alpha=.7)
        ax.axvline(summary["brake_end_s"], color="#999999", linestyle=":", alpha=.7)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="x", alpha=.15)
        ax.set_axisbelow(True)
    fig.text(.5, .018, "Assumed constant-speed leader and sufficient body clearance. Positions are shuttle centers; no passing or emergency stop.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .04, 1, 1))
    for extension in ("png", "pdf"):
        fig.savefig(output / f"fig1_following_timeline.{extension}", dpi=200)
    plt.close(fig)
