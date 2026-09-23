"""No-zone dispatch replay and post-hoc continuous-time conflict exposure.

Trajectories ignore other shuttles. Conflict penalties never feed back into
dispatch or routing; they are sensitivity estimates, not a safe traffic model.
"""
from dataclasses import asdict, dataclass
import csv
import heapq
import json
import math
import os
from pathlib import Path
import random
from statistics import mean, stdev

from .azure_static_zone_pilot import _load_batch, _sha256
from .azure_capacity_scalability import build_virtual_platter_work


@dataclass(frozen=True)
class Segment:
    shuttle: int
    task: int
    side: int
    phase: str
    start: float
    end: float
    x: float
    y: float
    vx: float = 0
    vy: float = 0
    ax: float = 0
    ay: float = 0

    def state(self, time):
        dt = time-self.start
        return (self.x+self.vx*dt+self.ax*dt*dt/2,
                self.y+self.vy*dt+self.ay*dt*dt/2,
                self.vx+self.ax*dt, self.vy+self.ay*dt)


def roots(a, b, c):
    if abs(a) < 1e-12:
        return [] if abs(b) < 1e-12 else [-c/b]
    disc = b*b-4*a*c
    if disc < -1e-12:
        return []
    disc = math.sqrt(max(0, disc))
    return [(-b-disc)/(2*a), (-b+disc)/(2*a)]


def close_intervals(a, b, x_clearance, y_clearance):
    """Exact intervals where two axis-aligned clearance rectangles overlap."""
    if a.side != b.side or a.shuttle == b.shuttle:
        return []
    start, end = max(a.start, b.start), min(a.end, b.end)
    if end-start <= 1e-9:
        return []
    xa, ya, va, wa = a.state(start)
    xb, yb, vb, wb = b.state(start)
    coefficients = [((a.ax-b.ax)/2, va-vb, xa-xb, x_clearance),
                    ((a.ay-b.ay)/2, wa-wb, ya-yb, y_clearance)]
    points = {0.0, end-start}
    for acc, velocity, offset, clearance in coefficients:
        for bound in (-clearance, clearance):
            points.update(r for r in roots(acc, velocity, offset-bound) if 0 < r < end-start)
    intervals = []
    ordered = sorted(points)
    for lo, hi in zip(ordered, ordered[1:]):
        t = (lo+hi)/2
        if all(abs(acc*t*t+velocity*t+offset) < clearance-1e-10 for acc, velocity, offset, clearance in coefficients):
            intervals.append((start+lo, start+hi))
    return intervals


def route(shuttle, task, side, phase, time, source, target, config):
    """Horizontal-first shortest Manhattan route, stop at every axis change."""
    x, y = source
    tx, ty = target
    segments = []
    distance = abs(tx-x)
    if distance > 1e-12:
        sign = 1 if tx > x else -1
        accel, vmax = config["acceleration_m_s2"], config["speed_m_s"]
        peak = min(vmax, math.sqrt(distance*accel))
        ta = peak/accel
        cruise = max(0, (distance-peak*peak/accel)/peak)
        v = 0.0
        for duration, acceleration in ((ta, sign*accel), (cruise, 0), (ta, -sign*accel)):
            if duration > 1e-12:
                segments.append(Segment(shuttle, task, side, phase, time, time+duration, x, y, v, 0, acceleration))
                x += v*duration+acceleration*duration**2/2
                v += acceleration*duration
                time += duration
        x = tx
    if abs(ty-y) > 1e-12:
        duration = abs(ty-y)/config["level_spacing_m"]*config["crab_s_per_level"]
        segments.append(Segment(shuttle, task, side, phase, time, time+duration, x, y, 0, (ty-y)/duration))
        time += duration
    return segments, time


def replay(work, config, seed, length):
    rng = random.Random(seed)
    levels, slots = config["levels"], config["mapping_slots_per_level"]
    cells = rng.sample(range(2*levels*slots), len(work))
    positions = {}
    for item, cell in zip(sorted(work, key=lambda w: w.virtual_platter_id), cells):
        side, local = divmod(cell, levels*slots)
        level, slot = divmod(local, slots)
        positions[item.virtual_platter_id] = (side, (slot+.5)/slots*length, level*config["level_spacing_m"])
    readers = [(side, 0.0, level*config["level_spacing_m"]) for side in (0, 1) for level in (1, 3, 5, 7)]
    shuttles = [dict(side=side, position=(x, y), free=0.0, idle=True) for side, x, y in readers]
    reader_free = [0.0]*8
    reader_intervals = [[] for _ in readers]
    pending = sorted(work, key=lambda w: w.first_request_index)
    segments, rows, queue = [], {}, []
    time = 0.0

    def stationary(sid, task, phase, start, end, position):
        if end > start:
            segments.append(Segment(sid, task, shuttles[sid]["side"], phase, start, end, *position))

    while pending or queue:
        while queue and queue[0][0] <= time+1e-9:
            event_time, kind, sid, task = heapq.heappop(queue)
            s, row = shuttles[sid], rows[task]
            if kind == 0:  # Complete return; shuttle can accept another task.
                s.update(idle=True, free=event_time, position=row["platter_position"])
            else:  # Reader arrivals are processed in chronological order.
                rid = row["reader"]
                position = readers[rid][1:]
                begin = max(event_time, reader_free[rid])
                stationary(sid, task, "reader_queue", event_time, begin, position)
                end = begin+config["reader_load_s"]+config["reader_mount_s"]+row["bytes"]/(1024**2*config["reader_mib_s"])+config["reader_unload_s"]
                stationary(sid, task, "reader_service", begin, end, position)
                reader_free[rid] = end
                reader_intervals[rid].append((begin, end))
                row["reader_queue_s"] = begin-event_time
                legs, returned = route(sid, task, s["side"], "return", end, position, row["platter_position"], config)
                segments.extend(legs)
                stationary(sid, task, "place", returned, returned+config["place_s"], row["platter_position"])
                row["end_s"] = returned+config["place_s"]
                heapq.heappush(queue, (row["end_s"], 0, sid, task))
        # Earliest pending task that has an idle shuttle on its physically reachable side.
        while pending:
            selection = next(((i, w) for i, w in enumerate(pending)
                              if any(s["idle"] and s["side"] == positions[w.virtual_platter_id][0] for s in shuttles)), None)
            if selection is None:
                break
            index, w = selection
            side, x, y = positions[w.virtual_platter_id]
            idle = [sid for sid, s in enumerate(shuttles) if s["idle"] and s["side"] == side]
            sid = min(idle, key=lambda i: (abs(shuttles[i]["position"][0]-x)+abs(shuttles[i]["position"][1]-y), i))
            s, task = shuttles[sid], w.virtual_platter_id
            pending.pop(index)
            stationary(sid, -1, "idle", s["free"], time, s["position"])
            distance = abs(s["position"][0]-x)+abs(s["position"][1]-y)
            assert distance == min(abs(shuttles[i]["position"][0]-x)+abs(shuttles[i]["position"][1]-y) for i in idle)
            legs, picked = route(sid, task, side, "fetch", time, s["position"], (x, y), config)
            segments.extend(legs)
            stationary(sid, task, "pick", picked, picked+config["pick_s"], (x, y))
            rid = min((i for i, r in enumerate(readers) if r[0] == side), key=lambda i: (abs(readers[i][1]-x)+abs(readers[i][2]-y), i))
            legs, arrival = route(sid, task, side, "delivery", picked+config["pick_s"], (x, y), readers[rid][1:], config)
            segments.extend(legs)
            rows[task] = dict(task=task, shuttle=sid, side=side, bytes=w.size_bytes,
                              logical_requests=w.logical_request_count, first_request=w.first_request_index,
                              start_s=time, reader=rid, platter_position=(x,y), reader_arrival_s=arrival,
                              dispatch_distance_m=distance, idle_candidates=len(idle))
            s["idle"] = False
            heapq.heappush(queue, (arrival, 1, sid, task))
        if queue:
            time = queue[0][0]
        elif pending:
            raise RuntimeError("No progress")
    horizon = max(r["end_s"] for r in rows.values())
    for sid, s in enumerate(shuttles):
        stationary(sid, -1, "idle", s["free"], horizon, s["position"])
    for intervals in reader_intervals:
        assert all(b[0] >= a[1]-1e-9 for a, b in zip(intervals, intervals[1:]))
    for sid, s in enumerate(shuttles):
        own = sorted((seg for seg in segments if seg.shuttle == sid), key=lambda seg: seg.start)
        previous_time, previous_position = 0.0, readers[sid][1:]
        for seg in own:
            assert math.isclose(seg.start, previous_time, abs_tol=1e-7)
            assert math.dist((seg.x, seg.y), previous_position) < 1e-7
            previous_time, previous_position = seg.end, seg.state(seg.end)[:2]
        assert math.isclose(previous_time, horizon, abs_tol=1e-7)
    assert len(rows) == len(work)
    assert sum(r["bytes"] for r in rows.values()) == sum(w.size_bytes for w in work)
    assert sum(r["logical_requests"] for r in rows.values()) == sum(w.logical_request_count for w in work)
    return segments, list(rows.values()), horizon


def exposure(segments, config):
    active, windows = [], {}
    for current in sorted(segments, key=lambda s: s.start):
        active = [p for p in active if p.end > current.start+1e-9]
        for previous in active:
            intervals = close_intervals(previous, current, config["clearance_x_m"], config["clearance_y_m"])
            for start, end in intervals:
                t = (start+end)/2
                v1, w1 = previous.state(t)[2:]
                v2, w2 = current.state(t)[2:]
                if abs(w1)+abs(w2) > 1e-9:
                    category = "crossing_or_crabbing"
                elif abs(v1) < 1e-9 or abs(v2) < 1e-9:
                    category = "moving_vs_stopped" if abs(v1)+abs(v2) > 1e-9 else "stopped_vs_stopped"
                else:
                    category = "head_on" if v1*v2 < 0 else "same_direction"
                pair = sorted(((previous.shuttle, previous.task, previous.phase), (current.shuttle, current.task, current.phase)))
                key = (*pair[0], *pair[1], category)
                windows.setdefault(key, []).append((start,end))
        active.append(current)
    events = []
    for (a, ta, pa, b, tb, pb, category), spans in windows.items():
        merged = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1]+1e-8:
                merged[-1][1] = max(end, merged[-1][1])
            else:
                merged.append([start,end])
        for start, end in merged:
            events.append(dict(shuttle_a=a, task_a=ta, phase_a=pa, shuttle_b=b, task_b=tb, phase_b=pb, kind=category, start_s=start, end_s=end, exposure_s=end-start))
    return sorted(events, key=lambda e: e["start_s"])


def csv_write(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run_study(config, root):
    validate_config(config)
    source = root / config["batch_path"]
    if _sha256(source) != config["batch_sha256"]:
        raise ValueError("Trace checksum mismatch")
    accesses = _load_batch(source)
    output = root / config["output_dir"]
    output.mkdir(parents=True, exist_ok=True)
    runs, all_events, penalty_rows, clearance_rows = [], [], [], []
    for seed in config["seeds"]:
        work = build_virtual_platter_work(accesses, config["platter_count"], seed)
        for length in config["lengths_m"]:
            segments, tasks, horizon = replay(work, config, seed, length)
            events = exposure(segments, config)
            for factor in (.5, 1, 1.5):
                measured = events if factor == 1 else exposure(segments, dict(config, clearance_x_m=config["clearance_x_m"]*factor, clearance_y_m=config["clearance_y_m"]*factor))
                affected_fetch = {e["task_"+label] for e in measured for label in ("a", "b") if e["phase_"+label] == "fetch"}
                clearance_rows.append(dict(seed=seed, length_m=length, clearance_multiplier=factor,
                                           fetch_affected_fraction=len(affected_fetch)/len(tasks)))
            touched = {t for e in events for t in (e["task_a"], e["task_b"]) if t >= 0}
            moving_kinds = {"fetch", "delivery", "return"}
            movement = sum(s.end-s.start for s in segments if s.phase in moving_kinds)
            row = dict(seed=seed, length_m=length, physical_tasks=len(tasks), logical_requests=sum(w.logical_request_count for w in work),
                       unique_bytes=sum(w.size_bytes for w in work), drain_s=horizon,
                       logical_throughput=sum(w.logical_request_count for w in work)/horizon,
                       affected_tasks=len(touched), affected_task_fraction=len(touched)/len(tasks),
                       conflict_episodes=len(events), movement_s=movement,
                       reader_queue_s=sum(r["reader_queue_s"] for r in tasks))
            for kind in config["penalty_s"]:
                row[kind+"_episodes"] = sum(e["kind"] == kind for e in events)
            for phase in ("fetch", "delivery", "return"):
                affected = {e["task_"+label] for e in events for label in ("a", "b") if e["phase_"+label] == phase}
                row[phase+"_affected_fraction"] = len(affected)/len(tasks)
            runs.append(row)
            all_events.extend(dict(seed=seed, length_m=length, **e) for e in events)
            # Deduplicate adjacent phase classifications to one charge per task pair;
            # use the maximum configured penalty in that pair, counted once globally.
            pairs = {}
            for e in events:
                key = (e["shuttle_a"], e["task_a"], e["shuttle_b"], e["task_b"])
                pairs[key] = max(pairs.get(key, 0), config["penalty_s"][e["kind"]])
            for multiplier in config["penalty_multipliers"]:
                extra = sum(pairs.values())*multiplier
                penalty_rows.append(dict(seed=seed, length_m=length, multiplier=multiplier,
                                         interacting_task_pairs=len(pairs), estimated_extra_shuttle_s=extra,
                                         extra_over_movement=extra/movement))
            if seed == config["seeds"][0]:
                folder = output / f"audit-{length:g}m"
                folder.mkdir(exist_ok=True)
                csv_write(folder / "tasks.csv", tasks)
                csv_write(folder / "trajectory.csv", [asdict(s) for s in segments])
    csv_write(output / "runs.csv", runs)
    csv_write(output / "conflicts.csv", all_events)
    csv_write(output / "penalty_sensitivity.csv", penalty_rows)
    csv_write(output / "clearance_sensitivity.csv", clearance_rows)
    aggregate = []
    for length in config["lengths_m"]:
        group = [r for r in runs if r["length_m"] == length]
        item = dict(length_m=length, runs=len(group))
        for metric in ("affected_task_fraction", "fetch_affected_fraction", "delivery_affected_fraction", "return_affected_fraction", "conflict_episodes", "drain_s", "movement_s", "reader_queue_s"):
            values = [r[metric] for r in group]
            item[metric+"_mean"] = mean(values)
            item[metric+"_std"] = stdev(values) if len(values)>1 else 0
        aggregate.append(item)
    csv_write(output / "aggregate.csv", aggregate)
    summary = dict(config=config, source=dict(requests=len(accesses), logical_bytes=sum(a.size_bytes for a in accesses)), aggregate=aggregate,
                   validation=dict(trace_checksum=True, task_and_byte_conservation=True, nearest_idle_dispatch=True,
                                   shuttle_trajectory_continuity=True, reader_serialization=True),
                   limitations=["Closed batch: original interarrival times not replayed.",
                                "Artificial seeded packing into fixed virtual platters; positions are not in Azure trace.",
                                "No-zone within each connected side only; Manhattan nearest-idle dispatch, nearest reader, horizontal-first route.",
                                "Unresolved collision-exposure replay; no physical safety guarantee.",
                                "Post-hoc penalty is total shuttle-time, not batch completion or throughput. No scheduling feedback.",
                                "Penalty values and body clearance are illustrative sensitivity assumptions, not Silica measurements."])
    (output / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    plot(aggregate, penalty_rows, config, output)
    lines = ["# Azure no-zone conflict exposure pilot", "", "## 設定", "",
             "使用本機已排序的 Azure head-100k read batch，整批在 t=0 可見。保留真實 object identity、bytes、重複存取，沿用 deterministic uniform packing 裝入 640 個 virtual platters，每片只服務一次。這不是原始 arrival-time replay。", "",
             "8 shuttles、8 readers，兩個不連通的 panel sides 各 4 台與 4 個 readers。Shuttle 可服務自己 panel 的全部高度與位置，沒有 static zone ownership。", "",
             "依最早 request 的 platter 順序派工；若其 panel 沒有空閒 shuttle，可先派另一側最早的工作。選 Manhattan 實體路徑距離最近的空閒 shuttle（平手取小 ID），reader 也取最近者。水平先走、再垂直 crabbing，水平包含加減速；每次換軸停車。讀完放回原位再接下一個工作。", "",
             "各 seed 使用相同物件分組與固定 side/level/normalized x，只有水平長度隨 2/16/64 m 改變。所有長度的每側每層 mapping slots 固定 100：本輪是 footprint sweep，不能當成真實 slot-density scaling。", "",
             "## 衝突如何定義", "",
             "用連續時間的軌跡判定兩台的中心間距是否同時低於 x=0.5 m、y=0.65 m。這是示例矩形占用範圍（車體+margin），不是 Silica 測得的尺寸。取放、reader queue、讀取期間和 idle 都繼續占位。", "",
             "圖中比例的分母是 640 個 tasks；fetch、delivery、return 分開計，每個 task 在該階段只算一次。完整服務受影響比例是聯集，不能把三個百分比相加。不同 phase/category 可分成多個 episode，episode 次數不是獨立碰撞數。", "",
             "## 結果（10 seeds 平均）", "", "| Side 長度 | Fetch 受影響 | Delivery 受影響 | Return 受影響 | 完整服務受影響 |", "| --- | --- | --- | --- | --- |"]
    for row in aggregate:
        group = [r for r in runs if r["length_m"] == row["length_m"]]
        lines.append(f"| {row['length_m']:g} m | {row['fetch_affected_fraction_mean']:.1%} | {row['delivery_affected_fraction_mean']:.1%} | {row['return_affected_fraction_mean']:.1%} | {mean(r['affected_task_fraction'] for r in group):.1%} |")
    lines += ["", "## Penalty 解讀", "",
              "預設 head-on=6 s、same-direction=2 s，其餘 stopped/crossing=3 s。這些僅借用小案例的量級，不是由軌跡求出的真正等待或繞行成本。每對 shuttle/task 只收一次最高類別 penalty，idle 以 task=-1 表示；再乘 0.5/1/2 做敏感度分析。", "",
              "輸出是累計額外 shuttle-seconds；沒有分配到個別 shuttle，也不改動後續路徑，因此不能換算成可信的 penalty-adjusted throughput。原本軌跡已存在未解決重疊，高受影響比例代表需要協調，不代表套固定 penalty 就能安全執行。", "",
              "## 必須保留的解讀限制", "",
              "- 不是實際碰撞機率，只是這個 trace/mapping/routing/clearance 下的潛在接觸比例。",
              "- Clearance、水平先走、固定 reader 位置都會強烈影響結果；clearance_sensitivity.csv 保留 0.5/1/1.5 倍的檢查。",
              "- 有些衝突涉及 parked robot 或 reader queue，單靠兩台迎面/跟車的小案例不足以估計它們的避障成本。",
              "- 這次沒有配對 static-zone traffic baseline，不能直接和舊 simulator 的 throughput 數字比較或宣稱 no-zone 輸贏。",
              "- 只有一個真實 batch；seeds 改變的是人工 placement，不代表十個獨立 workload samples。", "",
              "## 重現", "", "```bash",
              ".venv/bin/python scripts/run_no_zone_conflict.py",
              ".venv/bin/python -m unittest tests.test_no_zone_conflict -v", "```", "",
              "runs.csv / aggregate.csv：每 seed 與彙整數據。conflicts.csv：時刻、參與 shuttle/task/phase。audit-*m：第一個 seed 的完整派工與軌跡。summary.json：參數、來源和驗證。"]
    (output / "ANALYSIS_ZH.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return summary


def validate_config(config):
    if config["levels"] != 8:
        raise ValueError("This pilot fixes eight levels and four readers/shuttles per side")
    for key in ("platter_count", "mapping_slots_per_level"):
        if not isinstance(config[key], int) or config[key] <= 0:
            raise ValueError(f"Invalid {key}")
    if config["platter_count"] > 2*8*config["mapping_slots_per_level"]:
        raise ValueError("Not enough unique platter positions")
    for key in ("level_spacing_m", "speed_m_s", "acceleration_m_s2", "crab_s_per_level", "clearance_x_m", "clearance_y_m", "reader_mib_s"):
        if not math.isfinite(config[key]) or config[key] <= 0:
            raise ValueError(f"Invalid {key}")
    if not config["seeds"] or len(set(config["seeds"])) != len(config["seeds"]):
        raise ValueError("Seeds must be unique and nonempty")
    if not config["lengths_m"] or any(not math.isfinite(x) or x <= 0 for x in config["lengths_m"]):
        raise ValueError("Panel lengths must be positive")
    if set(config["penalty_s"]) != {"head_on", "same_direction", "moving_vs_stopped", "stopped_vs_stopped", "crossing_or_crabbing"}:
        raise ValueError("Penalty categories incomplete")
    values = list(config["penalty_s"].values())+config["penalty_multipliers"]+[config[k] for k in ("pick_s", "place_s", "reader_load_s", "reader_unload_s", "reader_mount_s")]
    if not config["penalty_multipliers"] or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("Costs must be nonnegative and finite")


def plot(aggregate, penalties, config, output):
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/glint-mplconfig")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    x = list(range(len(aggregate)))
    fig, axes = plt.subplots(1,2,figsize=(10,4.5))
    for offset, metric, color, label in ((-.25,"fetch","#327ba4","Fetch"),(0,"delivery","#569769","Delivery"),(.25,"return","#cc9042","Return")):
        axes[0].bar([i+offset for i in x], [r[metric+"_affected_fraction_mean"]*100 for r in aggregate], width=.24, color=color,
                    yerr=[r[metric+"_affected_fraction_std"]*100 for r in aggregate], capsize=3,label=label)
    axes[0].legend(frameon=False,fontsize=9)
    axes[0].set_ylim(0,100)
    axes[0].set_ylabel("Trips with potential conflict / all tasks (%)")
    axes[0].set_title("(a) No-zone path exposure",loc="left",fontsize=11)
    for factor in config["penalty_multipliers"]:
        values = [mean(r["extra_over_movement"]*100 for r in penalties if r["length_m"]==length and r["multiplier"]==factor) for length in config["lengths_m"]]
        axes[1].plot(x,values,marker="o",label=f"Penalty x{factor:g}")
    axes[1].set_ylabel("Estimated extra shuttle-time / movement (%)")
    axes[1].set_title("(b) Post-hoc penalty sensitivity",loc="left",fontsize=11)
    axes[1].legend(frameon=False)
    for ax in axes:
        ax.set_xticks(x, [f"{r['length_m']:g}" for r in aggregate])
        ax.set_xlabel("Panel-side length (m)")
        ax.spines[["top","right"]].set_visible(False)
        ax.set_axisbelow(True)
        ax.grid(axis="y",alpha=.2)
    fig.text(.5,.02,"Azure head-100k closed batch; synthetic platter mapping. Potential conflicts, not actual collisions. Error bars: seed SD.",ha="center",fontsize=8)
    fig.tight_layout(rect=(0,.07,1,1))
    for ext in ("pdf","png"):
        fig.savefig(output/f"fig1_no_zone_exposure.{ext}",dpi=200)
    plt.close(fig)
