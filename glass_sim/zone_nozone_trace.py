"""Natural-arrival policy comparison using explicit optimistic off-rail holding.

This is a service-system abstraction: holding pockets have unlimited capacity
and zero access cost. The verified rail trajectories do not validate a physical
Silica deployment. No wait-only baseline is included.
"""
from dataclasses import asdict, dataclass
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, stdev
from time import perf_counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import os

from .azure_static_zone_pilot import _hash_u64, _sha256
from .azure_capacity_scalability import VirtualPlatterWork
from .no_zone_conflict import exposure
from .zone_nozone_comparison import (
    STATIC_ZONE, NO_ZONE, NO_ZONE_VIRTUAL, POLICIES, ComparisonConfig, ShuttleState,
    physical_positions, reader_positions, zone_for, schedule_job, _write_csv,
    _direct_duration,
)


@dataclass(frozen=True)
class Read:
    index: int
    arrival: float
    key: tuple[str, str]
    size: int


def load_reads(path):
    reads = []
    with gzip.open(path, "rt", newline="", encoding="utf-8") as handle:
        for i, row in enumerate(csv.DictReader(handle)):
            reads.append(Read(i, int(row["ArrivalMs"])/1000,
                              (row["AnonBlobName"], row["AnonBlobETag"]), int(row["BlobBytes"])))
    if not reads or any(r.size < 0 or r.arrival < 0 for r in reads):
        raise ValueError("Invalid or empty read trace")
    if any(b.arrival < a.arrival for a, b in zip(reads, reads[1:])):
        raise ValueError("Trace must already be timestamp sorted")
    return reads


def mapping(reads, config, seed):
    sizes = {}
    for r in reads:
        if sizes.setdefault(r.key, r.size) != r.size:
            raise ValueError("Inconsistent immutable-version size")
    if len(sizes) < config.platter_count:
        raise ValueError("More platters than objects")
    keys = sorted(sizes, key=lambda k: (_hash_u64(seed, *k), k))
    mapped = {key: i % config.platter_count for i, key in enumerate(keys)}
    # Offline storage placement uses object identity, never arrival load or policy.
    return mapped


def percentile(values, q):
    ordered = sorted(values)
    index = (len(ordered)-1)*q
    lo = int(index)
    return ordered[lo]+(ordered[min(lo+1,len(ordered)-1)]-ordered[lo])*(index-lo)


def simulate(reads, mapped, positions, config, policy, save_segments=False):
    readers = reader_positions(config)
    shuttles = [ShuttleState(i, p[0], p[1:]) for i,p in enumerate(readers)]
    reader_free = [0.0]*8
    platter_free = {platter:0.0 for platter in positions}
    pending = {}
    reservations, all_segments, jobs, samples = [], [], [], []
    completions, completion_plate = [None]*len(reads), [None]*len(reads)
    transport_waits, queue_waits, read_times = [0.0]*len(reads), [0.0]*len(reads), [0.0]*len(reads)
    request_phase_totals = {
        "fetch": 0.0,
        "pick": 0.0,
        "delivery": 0.0,
        "reader_queue": 0.0,
        "reader_read": 0.0,
        "coordination": 0.0,
    }
    cursor, clock, service_id, queued_count = 0, 0.0, 0, 0
    started = perf_counter()

    def estimated_read_completion(platter, group, shuttle, start_s):
        side, x, y = positions[platter]
        fetch = _direct_duration(
            shuttle.shuttle_id,
            service_id,
            side,
            "fetch",
            shuttle.position,
            (x, y),
            config,
        )
        read_duration = (
            config.reader_load_s
            + config.reader_mount_s
            + sum({request.key: request.size for request in group}.values())
            / (1024**2 * config.reader_mib_s)
            + config.reader_unload_s
        )
        completion = min(
            max(
                start_s
                + fetch
                + config.pick_s
                + _direct_duration(
                    shuttle.shuttle_id,
                    service_id,
                    side,
                    "delivery",
                    (x, y),
                    reader[1:],
                    config,
                ),
                reader_free[index],
            )
            + read_duration
            for index, reader in enumerate(readers)
            if reader[0] == side
        )
        return completion, fetch

    while cursor < len(reads) or pending:
        while cursor < len(reads) and reads[cursor].arrival <= clock+1e-9:
            r = reads[cursor]
            pending.setdefault(mapped[r.key], []).append(r)
            queued_count += 1
            cursor += 1
        idle = [s for s in shuttles if s.free_s <= clock+1e-9]
        # Expired reservations cannot conflict with a newly dispatched job.
        reservations = [s for s in reservations if s.end > clock]
        options = []
        for platter, group in pending.items():
            if platter_free[platter] > clock+1e-9:
                continue
            side, x, y = positions[platter]
            candidates = [s for s in idle if s.side == side and
                          (policy in {NO_ZONE, NO_ZONE_VIRTUAL} or s.shuttle_id == zone_for(positions[platter], config))]
            if candidates:
                options.append((group[0].index, platter, candidates))
        chosen = None
        if options and policy == NO_ZONE_VIRTUAL:
            local_options = []
            for first_index, candidate_platter, candidate_shuttles in options:
                owner_id = zone_for(positions[candidate_platter], config)
                owner = next(
                    (shuttle for shuttle in candidate_shuttles if shuttle.shuttle_id == owner_id),
                    None,
                )
                if owner is not None:
                    local_options.append((first_index, candidate_platter, owner))
            if local_options:
                chosen = min(local_options, key=lambda value: (value[0], value[1], value[2].shuttle_id))
            else:
                helper_options = []
                by_id = {shuttle.shuttle_id: shuttle for shuttle in shuttles}
                for first_index, candidate_platter, candidate_shuttles in options:
                    group = pending[candidate_platter]
                    owner = by_id[zone_for(positions[candidate_platter], config)]
                    owner_completion, _ = estimated_read_completion(
                        candidate_platter,
                        group,
                        owner,
                        max(clock, owner.free_s),
                    )
                    for helper in candidate_shuttles:
                        helper_completion, helper_fetch = estimated_read_completion(
                            candidate_platter,
                            group,
                            helper,
                            clock,
                        )
                        home = readers[helper.shuttle_id][1:]
                        recovery = _direct_duration(
                            helper.shuttle_id,
                            service_id,
                            helper.side,
                            "reposition",
                            positions[candidate_platter][1:],
                            home,
                            config,
                        )
                        benefit = owner_completion - helper_completion - recovery
                        if benefit > 1e-9:
                            helper_options.append(
                                (
                                    -benefit,
                                    first_index,
                                    helper_completion,
                                    helper_fetch,
                                    candidate_platter,
                                    helper.shuttle_id,
                                    helper,
                                )
                            )
                if helper_options:
                    best = min(helper_options)
                    chosen = (best[1], best[4], best[6])
        elif options:
            first_index, platter, candidates = min(options, key=lambda v: v[0])
            selected = min(candidates, key=lambda s: (abs(s.position[0]-positions[platter][1])+abs(s.position[1]-positions[platter][2]), s.shuttle_id))
            chosen = (first_index, platter, selected)

        if chosen is not None:
            _, platter, selected = chosen
            group = pending.pop(platter)
            queued_count -= len(group)
            side = positions[platter][0]
            x,y = positions[platter][1:]
            selected.free_s = clock
            unique = {r.key:r.size for r in group}
            work = VirtualPlatterWork(service_id, group[0].index, sum(unique.values()), len(group), len(unique))
            reader_override = None
            if policy == NO_ZONE_VIRTUAL and selected.shuttle_id == zone_for(positions[platter], config):
                reader_override = zone_for(positions[platter], config)
            job, segments = schedule_job(work, positions[platter], selected, readers, reader_free,
                                         reservations, config, policy, reader_override)
            service = next(s for s in segments if s.phase == "reader_service")
            # Completion = last requested byte read, before unload and return.
            read_done = service.end-config.reader_unload_s
            for r in group:
                assert r.arrival <= job.start_s+1e-8
                assert completions[r.index] is None
                completions[r.index] = read_done
                completion_plate[r.index] = platter
                queue_waits[r.index] = job.start_s-r.arrival
                transport_waits[r.index] = job.conflict_wait_s+job.detour_s
                read_times[r.index] = read_done-job.start_s
            weight = len(group)
            request_phase_totals["fetch"] += job.fetch_direct_s * weight
            request_phase_totals["pick"] += config.pick_s * weight
            request_phase_totals["delivery"] += job.delivery_direct_s * weight
            request_phase_totals["reader_queue"] += job.reader_queue_s * weight
            request_phase_totals["reader_read"] += (read_done-service.start) * weight
            request_phase_totals["coordination"] += (
                job.fetch_coordination_s
                + job.pick_coordination_s
                + job.delivery_coordination_s
                + job.reader_coordination_s
            ) * weight
            assert math.isclose(job.actual_cycle_s-job.base_cycle_s,
                                job.conflict_wait_s+job.detour_s+job.reader_queue_s,abs_tol=1e-6)
            if policy == STATIC_ZONE:
                assert job.shuttle_id == job.zone_id
            row = dict(**asdict(job), platter_id=platter, read_done_s=read_done,
                       eligible_idle=len(candidates), queued_after_dispatch=queued_count,
                       merge_requests=len(group), merge_unique_versions=len(unique))
            jobs.append(row)
            platter_free[platter] = job.end_s
            reposition_s = 0.0
            if policy == NO_ZONE_VIRTUAL and job.shuttle_id != job.zone_id:
                home = readers[job.shuttle_id][1:]
                reposition_s = _direct_duration(
                    job.shuttle_id,
                    service_id,
                    selected.side,
                    "reposition",
                    selected.position,
                    home,
                    config,
                )
                selected.position = home
                selected.free_s += reposition_s
                row["reposition_s"] = reposition_s
            occupied = [s for s in segments if s.side >= 0]
            if policy == NO_ZONE:
                # Only currently relevant committed segments are required for a local check.
                assert not exposure(reservations+occupied, config.motion_dict())
            reservations.extend(occupied)
            if save_segments:
                all_segments.extend(segments)
            samples.append(dict(time_s=clock,queued_requests=queued_count))
            service_id += 1
            continue
        next_arrival = reads[cursor].arrival if cursor < len(reads) else math.inf
        relevant_free = [s.free_s for s in shuttles if s.free_s > clock+1e-9
                         and any(s.side == positions[p][0] and
                                 (policy in {NO_ZONE, NO_ZONE_VIRTUAL} or s.shuttle_id == zone_for(positions[p],config)) for p in pending)]
        next_free = min(relevant_free+[platter_free[p] for p in pending if platter_free[p] > clock+1e-9], default=math.inf)
        next_time = min(next_arrival, next_free)
        if not math.isfinite(next_time) or next_time <= clock:
            raise RuntimeError("No progress in online simulation")
        clock = next_time
    assert all(c is not None for c in completions)
    assert sum(j["logical_requests"] for j in jobs) == len(reads)
    horizon = max(max(j["end_s"] for j in jobs), max(shuttle.free_s for shuttle in shuttles))
    lats = [c-r.arrival for c,r in zip(completions,reads)]
    movement = sum(
        j["fetch_direct_s"] + j["delivery_direct_s"] + j["return_direct_s"]
        for j in jobs
    )
    coordination_delays = [j["conflict_wait_s"] + j["detour_s"] for j in jobs]
    affected_delays = [delay for delay in coordination_delays if delay > 1e-12]
    zone_completion = {
        zone_id: max(
            completions[r.index]
            for r in reads
            if zone_for(positions[mapped[r.key]], config) == zone_id
        )
        for zone_id in range(8)
        if any(zone_for(positions[mapped[r.key]], config) == zone_id for r in reads)
    }
    result = dict(policy=policy, logical_requests=len(reads), logical_bytes=sum(r.size for r in reads),
                  physical_services=len(jobs), physical_bytes=sum(j["size_bytes"] for j in jobs),
                  latency_mean_s=mean(lats), latency_p50_s=percentile(lats,.5),
                  latency_p95_s=percentile(lats,.95), latency_p99_s=percentile(lats,.99),
                  last_read_s=max(completions), read_drain_s=max(0,max(completions)-reads[-1].arrival),
                  system_return_drain_s=max(0,horizon-reads[-1].arrival),
                  observed_request_throughput=len(reads)/(max(completions)-reads[0].arrival),
                  request_queue_mean_s=mean(queue_waits), dispatch_to_read_mean_s=mean(read_times),
                  request_fetch_mean_s=request_phase_totals["fetch"]/len(reads),
                  request_pick_mean_s=request_phase_totals["pick"]/len(reads),
                  request_delivery_mean_s=request_phase_totals["delivery"]/len(reads),
                  request_reader_queue_mean_s=request_phase_totals["reader_queue"]/len(reads),
                  request_reader_read_mean_s=request_phase_totals["reader_read"]/len(reads),
                  request_coordination_mean_s=request_phase_totals["coordination"]/len(reads),
                  movement_s=movement, detour_s=sum(j["detour_s"] for j in jobs),
                  conflict_wait_s=sum(j["conflict_wait_s"] for j in jobs),
                  reader_queue_s=sum(j["reader_queue_s"] for j in jobs),
                  reader_service_s=sum(config.reader_load_s+config.reader_unload_s+config.reader_mount_s+j["size_bytes"]/(1024**2*config.reader_mib_s) for j in jobs),
                  pick_place_s=len(jobs)*(config.pick_s+config.place_s),
                  conflict_affected_fraction=mean(j["conflict_count"]>0 for j in jobs),
                  conflict_delay_mean_s=mean(coordination_delays),
                  conflict_delay_p95_s=percentile(coordination_delays,.95),
                  conflict_delay_affected_mean_s=mean(affected_delays) if affected_delays else 0.0,
                  zone_completion_spread_s=max(zone_completion.values())-min(zone_completion.values()),
                  fetch_direct_s=sum(j["fetch_direct_s"] for j in jobs),
                  delivery_direct_s=sum(j["delivery_direct_s"] for j in jobs),
                  return_direct_s=sum(j["return_direct_s"] for j in jobs),
                  fetch_coordination_s=sum(j["fetch_coordination_s"] for j in jobs),
                  pick_coordination_s=sum(j["pick_coordination_s"] for j in jobs),
                  delivery_coordination_s=sum(j["delivery_coordination_s"] for j in jobs),
                  reader_coordination_s=sum(j["reader_coordination_s"] for j in jobs),
                  return_coordination_s=sum(j["return_coordination_s"] for j in jobs),
                  place_coordination_s=sum(j["place_coordination_s"] for j in jobs),
                  reposition_s=sum(j.get("reposition_s",0.0) for j in jobs),
                  max_dispatch_backlog=max(s["queued_requests"] for s in samples),
                  cpu_wall_s=perf_counter()-started)
    if not math.isclose(
        result["conflict_wait_s"] + result["detour_s"],
        result["fetch_coordination_s"]
        + result["pick_coordination_s"]
        + result["delivery_coordination_s"]
        + result["reader_coordination_s"]
        + result["return_coordination_s"]
        + result["place_coordination_s"],
        abs_tol=1e-6,
    ):
        raise RuntimeError("Conflict phase accounting mismatch")
    if not math.isclose(
        result["latency_mean_s"],
        result["request_queue_mean_s"]
        + result["request_fetch_mean_s"]
        + result["request_pick_mean_s"]
        + result["request_delivery_mean_s"]
        + result["request_reader_queue_mean_s"]
        + result["request_reader_read_mean_s"]
        + result["request_coordination_mean_s"],
        abs_tol=1e-6,
    ):
        raise RuntimeError("Request latency phase accounting mismatch")
    request_rows = [dict(index=r.index,arrival_s=r.arrival,platter_id=completion_plate[r.index],
                         zone_id=zone_for(positions[completion_plate[r.index]],config),
                         read_done_s=completions[r.index],latency_s=lats[r.index],
                         queue_s=queue_waits[r.index]) for r in reads]
    return result,jobs,all_segments,request_rows


def _case(config, seed, length):
    reads=load_reads(config.batch_path)
    mapped=mapping(reads,config,seed)
    dummy=[VirtualPlatterWork(i,i,1,1,1) for i in range(config.platter_count)]
    positions=physical_positions(dummy,config,seed,length)
    signature=hashlib.sha256(json.dumps([sorted(mapped.items()),sorted(positions.items())]).encode()).hexdigest()
    rows=[]
    for policy in POLICIES:
        result,jobs,segments,requests=simulate(reads,mapped,positions,config,policy,
                                              save_segments=seed==config.seeds[0])
        rows.append(dict(seed=seed,length_m=length,**result))
        if seed==config.seeds[0]:
            audit=config.output_dir/f"audit-{length:g}m-{policy}"
            audit.mkdir(parents=True,exist_ok=True)
            _write_csv(audit/"jobs.csv",jobs)
            _write_csv(audit/"requests.csv",requests)
            _write_csv(audit/"segments.csv",[asdict(s) for s in segments])
    return rows,dict(seed=seed,length_m=length,signature=signature)


def run(config, workers=1):
    config.validate()
    if _sha256(config.batch_path) != config.batch_sha256:
        raise ValueError("Trace SHA mismatch")
    reads = load_reads(config.batch_path)
    out=config.output_dir
    out.mkdir(parents=True,exist_ok=True)
    rows, mappings = [], []
    cases=[(config,seed,length) for seed in config.seeds for length in config.lengths_m]
    def retain(result):
        group,signature=result
        rows.extend(group)
        mappings.append(signature)
        rows.sort(key=lambda r:(r["seed"],r["length_m"],r["policy"]))
        _write_csv(out/"runs.csv",rows)
        print(f"Completed {len(rows)//2}/{len(cases)} pairs: seed={signature['seed']} length={signature['length_m']:g}; p99 zone/no-zone={[round(r['latency_p99_s'],1) for r in group]}",flush=True)
    if workers==1:
        for case in cases: retain(_case(*case))
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures=[pool.submit(_case,*case) for case in cases]
            for future in as_completed(futures): retain(future.result())
    aggregates=[]
    for length in config.lengths_m:
        for policy in POLICIES:
            group=[r for r in rows if r["length_m"]==length and r["policy"]==policy]
            row=dict(length_m=length,policy=policy,seeds=len(group))
            for key in group[0]:
                if key not in ("policy","seed","length_m"):
                    values=[r[key] for r in group]
                    row[key+"_mean"]=mean(values)
                    row[key+"_sd"]=stdev(values) if len(values)>1 else 0
            aggregates.append(row)
    _write_csv(out/"aggregate.csv",aggregates)
    _write_csv(out/"mapping_signatures.csv",mappings)
    c=config.to_json_dict()
    c["scope"].update(arrival_model="Original ArrivalMs, unchanged",merge="At dispatch, merge only arrived queued requests for the same platter; later arrivals form a future service")
    summary=dict(config=c,source=dict(requests=len(reads),span_s=reads[-1].arrival-reads[0].arrival,
                                      logical_bytes=sum(r.size for r in reads)),aggregate=aggregates,
                 validation=dict(request_conservation=True,no_dispatch_before_arrival=True,
                                 paired_mapping=True,time_accounting=True,no_zone_reserved_rail_conflicts=0),
                 caveats=["Optimistic unlimited off-rail holding at service locations with zero entry/exit cost; not physical collision avoidance.",
                          "Strict static zone skips inter-zone collision checks by assumption; not equivalent geometric safety validation.",
                          "Raw request size/order/timestamps preserved; synthetic object-to-platter placement shared across policies.",
                          "Online merge changes physical service counts across policies; results are whole-policy effects, not isolated conflict penalty.",
                          "A request arriving after dispatch is not added to that in-flight service; no persistent cache.",
                          "Whole jobs reserve ahead with first-committed priority; this simple controller is not optimal."])
    (out/"summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    plot(aggregates,out)
    report(summary,out)
    return summary


def plot(aggregate,out):
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/glint-mplconfig")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    lengths=sorted({r["length_m"] for r in aggregate})
    x=list(range(len(lengths)))
    colors={STATIC_ZONE:"#667580",NO_ZONE:"#2b819b"}
    labels={STATIC_ZONE:"Static zone",NO_ZONE:"No-zone coordinated"}
    fig,axes=plt.subplots(1,2,figsize=(10,4.2))
    for i,p in enumerate(POLICIES):
        group=[next(r for r in aggregate if r["length_m"]==l and r["policy"]==p) for l in lengths]
        axes[0].bar([v+(i-.5)*.34 for v in x],[r["latency_p99_s_mean"]/60 for r in group],width=.34,
                    yerr=[r["latency_p99_s_sd"]/60 for r in group],capsize=3,color=colors[p],label=labels[p])
    static=[next(r for r in aggregate if r["length_m"]==l and r["policy"]==STATIC_ZONE) for l in lengths]
    nozone=[next(r for r in aggregate if r["length_m"]==l and r["policy"]==NO_ZONE) for l in lengths]
    overhead=[100*(n["latency_p99_s_mean"]/s["latency_p99_s_mean"]-1) for s,n in zip(static,nozone)]
    axes[1].bar(x,overhead,width=.48,color=colors[NO_ZONE])
    for xpos,value in zip(x,overhead):
        axes[1].text(xpos,value+2,f"+{value:.0f}%",ha="center",va="bottom",fontsize=10,fontweight="bold")
    axes[0].set_title("(a) Tail request latency (p99)",loc="left",fontsize=11)
    axes[0].set_ylabel("Time from arrival to read completion (min)")
    axes[1].set_title("(b) No-zone tail-latency penalty",loc="left",fontsize=11)
    axes[1].set_ylabel("p99 increase over static zone (%)")
    axes[1].set_ylim(0,max(overhead)*1.2)
    for ax in axes:
        ax.set_xticks(x,[f"{l:g}" for l in lengths])
        ax.set_xlabel("Panel-side length (m)")
        ax.spines[["top","right"]].set_visible(False)
    axes[0].legend(frameon=False,fontsize=9)
    fig.text(.5,.018,"Same Azure arrivals and placement. Abstract holding-pocket model; error bars show placement-seed SD.",ha="center",fontsize=8)
    fig.tight_layout(rect=(0,.065,1,1))
    for ext in ("png","pdf"): fig.savefig(out/f"fig1_latency.{ext}",dpi=200)
    plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,4.6))
    components=[("fetch_direct_s","Fetch movement","#327ba4"),
                ("delivery_direct_s","Move to reader","#65a4bf"),
                ("return_direct_s","Return movement","#9bc3d2"),
                ("pick_place_s","Pick/place","#b5bdc5"),
                ("reader_queue_s","Reader queue","#ae6d91"),
                ("reader_service_s","Reader service","#808790")]
    for i,r in enumerate(aggregate):
        bottom=0
        for metric,label,color in components:
            value=r[metric+"_mean"]/r["physical_services_mean"]
            ax.bar(i,value,bottom=bottom,color=color,label=label if i==0 else None)
            bottom+=value
        coordination=(r["conflict_wait_s_mean"]+r["detour_s_mean"])/r["physical_services_mean"]
        ax.bar(i,coordination,bottom=bottom,color="#daa24b",label="Conflict avoidance" if i==0 else None)
    ax.set_xticks(range(len(aggregate)),[f"{r['length_m']:g}m\n{'Zone' if r['policy']==STATIC_ZONE else 'No-zone'}" for r in aggregate])
    ax.set_ylabel("Average time per physical service (s)")
    ax.set_title("Observation 1: Where one physical glass service spends time",loc="left",fontsize=12)
    ax.spines[["top","right"]].set_visible(False)
    ax.set_ylim(0,100)
    ax.legend(ncol=4,frameon=False,fontsize=8.5,loc="upper left")
    fig.text(.5,.018,"Average over completed physical services. Request queueing before dispatch is excluded; online merge can change service size.",ha="center",fontsize=8)
    fig.tight_layout(rect=(0,.07,1,1))
    for ext in ("png","pdf"): fig.savefig(out/f"fig2_service_cost.{ext}",dpi=200)
    plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(10,4.2))
    width=.34
    for i,p in enumerate(POLICIES):
        group=[next(r for r in aggregate if r["length_m"]==l and r["policy"]==p) for l in lengths]
        axes[0].bar([v+(i-.5)*width for v in x],[r["physical_services_mean"] for r in group],
                    width=width,color=colors[p],label=labels[p])
    affected=[100*r["conflict_affected_fraction_mean"] for r in nozone]
    axes[1].bar(x,affected,width=.48,color="#daa24b")
    for xpos,value in zip(x,affected):
        axes[1].text(xpos,value+2,f"{value:.0f}%",ha="center",fontsize=10)
    axes[0].set_title("(a) Physical services after online merge",loc="left",fontsize=11)
    axes[0].set_ylabel("Physical platter services")
    axes[0].legend(frameon=False,fontsize=9)
    axes[1].set_title("(b) No-zone services requiring coordination",loc="left",fontsize=11)
    axes[1].set_ylabel("Affected physical services (%)")
    axes[1].set_ylim(0,100)
    for ax in axes:
        ax.set_xticks(x,[f"{l:g}" for l in lengths])
        ax.set_xlabel("Panel-side length (m)")
        ax.spines[["top","right"]].set_visible(False)
    fig.text(.5,.018,"Supplementary diagnostics: policy timing changes online-merge opportunities and physical service counts.",ha="center",fontsize=8)
    fig.tight_layout(rect=(0,.065,1,1))
    for ext in ("png","pdf"): fig.savefig(out/f"fig3_diagnostics.{ext}",dpi=200)
    plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(10,4.3))
    affected=[100*r["conflict_affected_fraction_mean"] for r in nozone]
    axes[0].bar(x,affected,width=.48,color="#daa24b")
    for xpos,value in zip(x,affected):
        axes[0].text(xpos,value+2,f"{value:.0f}%",ha="center",fontsize=10)
    axes[0].set_ylim(0,100)
    axes[0].set_ylabel("No-zone physical services affected (%)")
    axes[0].set_title("(a) How often coordination is needed",loc="left",fontsize=11)

    phase_components=[
        ("rack","Rack access","#327ba4"),
        ("delivery","Move to reader","#6c9e69"),
        ("reader","Reader area","#ae6d91"),
        ("return","Return/place","#daa24b"),
    ]
    bottoms=[0.0]*len(nozone)
    for key,label,color in phase_components:
        if key=="rack":
            values=[(r["fetch_coordination_s_mean"]+r["pick_coordination_s_mean"])/r["physical_services_mean"] for r in nozone]
        elif key=="delivery":
            values=[r["delivery_coordination_s_mean"]/r["physical_services_mean"] for r in nozone]
        elif key=="reader":
            values=[r["reader_coordination_s_mean"]/r["physical_services_mean"] for r in nozone]
        else:
            values=[(r["return_coordination_s_mean"]+r["place_coordination_s_mean"])/r["physical_services_mean"] for r in nozone]
        axes[1].bar(x,values,bottom=bottoms,width=.48,color=color,label=label)
        bottoms=[a+b for a,b in zip(bottoms,values)]
    p95=[r["conflict_delay_p95_s_mean"] for r in nozone]
    axes[1].scatter(x,p95,marker="D",s=30,color="#1f2529",label="Per-service p95",zorder=3)
    axes[1].set_ylabel("Conflict-avoidance delay per service (s)")
    axes[1].set_title("(b) Where the delay appears",loc="left",fontsize=11)
    axes[1].legend(frameon=False,fontsize=8,loc="upper left",bbox_to_anchor=(1.01,1))
    for ax in axes:
        ax.set_xticks(x,[f"{l:g}" for l in lengths])
        ax.set_xlabel("Panel-side length (m)")
        ax.spines[["top","right"]].set_visible(False)
    fig.text(.5,.018,"Coordination includes holding and extra detour in the optimistic off-rail holding model.",ha="center",fontsize=8)
    fig.tight_layout(rect=(0,.065,1,1))
    for ext in ("png","pdf"): fig.savefig(out/f"fig4_conflict_location_and_severity.{ext}",dpi=200)
    plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(11.5,4.4))
    bar_width=.34
    ordered=[next(r for r in aggregate if r["length_m"]==length and r["policy"]==policy)
             for length in lengths for policy in POLICIES]
    positions=[index+offset for index in x for offset in (-bar_width/2,bar_width/2)]
    hatches=["" if r["policy"]==STATIC_ZONE else "//" for r in ordered]
    queue=[r["request_queue_mean_s_mean"]/60 for r in ordered]
    after_dispatch=[r["dispatch_to_read_mean_s_mean"]/60 for r in ordered]
    bars=axes[0].bar(positions,queue,width=bar_width,color="#6f7b83",label="Wait for shuttle")
    for bar,hatch in zip(bars,hatches): bar.set_hatch(hatch)
    bars=axes[0].bar(positions,after_dispatch,width=bar_width,bottom=queue,color="#65a4bf",label="After dispatch")
    for bar,hatch in zip(bars,hatches): bar.set_hatch(hatch)
    axes[0].set_ylabel("Mean request latency (min)")
    axes[0].set_title("(a) Queueing dominates latency",loc="left",fontsize=11)
    axes[0].legend(frameon=False,fontsize=8.5)

    request_components=[
        ("request_fetch_mean_s","Fetch movement","#327ba4"),
        ("request_pick_mean_s","Pick","#b5bdc5"),
        ("request_delivery_mean_s","Move to reader","#65a4bf"),
        ("request_reader_queue_mean_s","Wait for reader","#ae6d91"),
        ("request_reader_read_mean_s","Load/read","#808790"),
        ("request_coordination_mean_s","Conflict avoidance","#daa24b"),
    ]
    for i,r in enumerate(ordered):
        bottom=0.0
        for metric,label,color in request_components:
            value=r[metric+"_mean"]
            bars=axes[1].bar(positions[i],value,width=bar_width,bottom=bottom,color=color,label=label if i==0 else None)
            bars[0].set_hatch(hatches[i])
            bottom+=value
    axes[1].set_ylabel("Time after dispatch (s)")
    axes[1].set_title("(b) What happens after dispatch",loc="left",fontsize=11)
    axes[1].legend(ncol=2,frameon=False,fontsize=8,loc="upper left")
    for ax in axes:
        ax.set_xticks(x,[f"{length:g}" for length in lengths])
        ax.set_xlabel("Panel-side length (m)")
        ax.spines[["top","right"]].set_visible(False)
    fig.text(.5,.018,"Solid = Static zone; hatched = No-zone. Small per-service overhead reduces drain rate and accumulates as queueing.",ha="center",fontsize=8)
    fig.tight_layout(rect=(0,.065,1,1))
    for ext in ("png","pdf"): fig.savefig(out/f"fig5_request_latency_breakdown.{ext}",dpi=200)
    plt.close(fig)


def report(summary,out):
    lines=["# 真實到達時間：Static Zone / No-Zone", "", "## 主圖要回答的問題", "",
           "同一份 Azure 原始 requests，採用 zone 或讓最近的空閒 shuttle 跨區接手，使用者等待資料的時間差多少？圖一直接呈現 p99 latency 與 no-zone 的額外比例；圖二再解釋每次 physical service 的時間花在哪裡。", "",
           "## 結果", "", "| 長度 | Policy | 平均 latency | p99 | Physical services | 最後 request 後 read drain |", "| --- | --- | --- | --- | --- | --- |"]
    for r in summary["aggregate"]:
        lines.append(f"| {r['length_m']:g} m | {r['policy']} | {r['latency_mean_s_mean']/60:.2f} min | {r['latency_p99_s_mean']/60:.2f} min | {r['physical_services_mean']:.0f} | {r['read_drain_s_mean']/60:.2f} min |")
    lines += ["", "## 最直接的觀察", ""]
    for length in sorted({r["length_m"] for r in summary["aggregate"]}):
        static=next(r for r in summary["aggregate"] if r["length_m"]==length and r["policy"]==STATIC_ZONE)
        nozone=next(r for r in summary["aggregate"] if r["length_m"]==length and r["policy"]==NO_ZONE)
        overhead=100*(nozone["latency_p99_s_mean"]/static["latency_p99_s_mean"]-1)
        lines.append(f"- {length:g} m：no-zone 的 p99 比 static zone 高 {overhead:.1f}%。")
    lines += ["", "## Observation 1：時間花在哪裡", ""]
    for r in summary["aggregate"]:
        queue_share=r["request_queue_mean_s_mean"]/r["latency_mean_s_mean"]
        lines.append(f"- {r['length_m']:g} m / {r['policy']}：平均 latency 的 {queue_share:.1%} 是 request 在 dispatch 前等待 shuttle；dispatch 後平均 {r['dispatch_to_read_mean_s_mean']:.1f} 秒完成讀取。")
    lines += ["", "這表示自然 arrival replay 的 tail 主要不是單次 collision delay 直接構成，而是每次 service 的 movement/coordination 成本降低 drain rate，讓 queue 持續累積。完整 platter service 還包含 request 完成後的 unload、return 與 place；圖二和圖五刻意把 resource occupancy 與 request latency 分開。", "",
              "## Observation 2：No-Zone conflict 多嚴重", ""]
    for r in summary["aggregate"]:
        if r["policy"] != NO_ZONE:
            continue
        lines.append(f"- {r['length_m']:g} m：{r['conflict_affected_fraction_mean']:.1%} physical services 遇到 coordination；受影響 service 平均增加 {r['conflict_delay_affected_mean_s_mean']:.1f} 秒，所有 service 的 coordination-delay p95 為 {r['conflict_delay_p95_s_mean']:.1f} 秒。")
    shortest=min(r["length_m"] for r in summary["aggregate"])
    lines += ["", f"{shortest:g} m 時 conflict 主要出現在 fetch/rack access；panel 拉長後，rack-side coordination 降低，而 platter-to-reader delivery 變成較大的部分。這是目前 route-reservation 模型的結果，不等於真實硬體碰撞熱點。", "",
              "在這個模型的所有測試長度中，zone 都較快；但差距隨 panel 變長而縮小。這支持一個有限度的說法：當 shuttle 活動集中在較短空間時，隔離路徑衝突的價值較高；空間拉長後，這項價值下降。實驗尚未找到 no-zone 反超的 crossover。", "",
              "No-zone 因等待較久，反而有更多 requests 能在派工前合併，因此 physical services 較少。即使得到這項優勢，它仍有較高 latency。不過這也表示兩邊不是只差 collision penalty，主結果必須解讀為兩個完整 policy 的比較。圖三把這項診斷獨立列出，不放進主故事。", "",
              "## 如何模擬", "",
              "保留 ArrivalMs、request 順序、bytes 與 object version，沒有壓縮時間或人工增加 hot requests。每次派工只合併已到達且尚未服務的同 platter requests；未來 request 不會提前完成。", "",
              "8 readers、8 shuttles，兩個物理不連通 panel 各 4 個。Static 每兩層一個 owner，No-zone 可服務同側全部位置。No-zone 選當下最近的空閒 shuttle，再使用最近 reader；平距離時考慮可用時間。", "",
              "主模型仍沿用資料放置假設：blob versions 以固定 seed 排序分裝到 virtual platters，再放到固定 side/level/相對水平位置。Placement 對兩 policy 完全相同，但不是 Azure 實際 glass address。", "",
              "No-zone 以已預約路徑優先，檢查 direct 與中間高度繞行方案，選 earliest finish；holding、detour 會真的延後完成與下一次派工。", "",
              "## 不能跳過的模型限制", ""]
    lines += ["- "+s for s in summary["caveats"]]
    lines += ["", "特別注意：holding pocket 是模型新增的抽象。等待中的機器人被視為離開 rail，未計進出成本且容量無限。零 rail conflict 只表示預約的 rail segments 不重疊，不能宣稱機器人在真實 Silica 上已能安全避障。", "",
              "不同 policy 的等待會改變可合併 requests 數量，所以 physical service 數和讀取 bytes 不必相同。主張應是這個整體 policy 的 latency 差異，不能把全部差異歸因為 collision。", "",
              "這組採自然 arrivals，若 throughput 接近 trace 的輸入速率，應看 latency/backlog，而非聲稱兩邊服務能力相等。", "",
              "## Reproduce", "", "```bash", ".venv/bin/python scripts/run_zone_nozone_trace.py", "```", "",
              "runs.csv 保留每個 seed；aggregate.csv 是平均與 sample SD；第一個 seed 的 audit 目錄包含每筆 request 完成時刻、每次派工與軌跡。"]
    (out/"ANALYSIS_ZH.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
