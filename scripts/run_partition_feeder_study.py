"""Generate the registered single-partition study, plots and deck input data."""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
from statistics import mean, stdev
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from glass_sim.partition_feeder_study import Config, PartitionSimulation, make_requests


KEYS = ('experiment', 'pattern', 'arrival_mode', 'shuttles', 'policy', 'buffer_slots', 'length_m', 'read_s')
LABELS = {'zone': 'Zone', 'nonzone_fifo': 'Non-Zone FIFO', 'nonzone_local': 'Non-Zone lookahead'}
COLORS = {'zone': '#547465', 'nonzone_fifo': '#c17a3b', 'nonzone_local': '#75639b'}


def csv_write(path, rows):
    if not rows:
        return
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def cases(raw):
    base = Config(**raw['model'])
    e = raw['provision']
    for n, length, read in itertools.product(e['shuttles'], e['lengths_m'], e['read_s']):
        yield 'E1', 'uniform', None, replace(base, shuttles=n, length_m=length, read_s=read, policy='zone', buffer_slots=4)
    e = raw['coordination']
    for n, policy, pattern in itertools.product(e['shuttles'], LABELS, e['patterns']):
        yield 'E2', pattern, None, replace(base, shuttles=n, length_m=e['length_m'], read_s=e['read_s'], policy=policy, buffer_slots=4)
    e = raw['buffer']
    for n, policy, capacity, read in itertools.product(e['shuttles'], ['zone', 'nonzone_fifo'], e['capacities'], e['read_s']):
        yield 'E3', 'uniform', None, replace(base, shuttles=n, length_m=e['length_m'], read_s=read, policy=policy, buffer_slots=capacity)
    e = raw['online']
    for policy, capacity, pattern in itertools.product(['zone', 'nonzone_fifo'], e['capacities'], e['patterns']):
        c = replace(base, shuttles=e['shuttles'], length_m=e['length_m'], read_s=e['read_s'], policy=policy, buffer_slots=capacity)
        yield 'E4', pattern, e['offered_reader_load']/c.cycle_s, c


def aggregate(rows):
    groups = {}
    for r in rows:
        groups.setdefault(tuple(r[k] for k in KEYS), []).append(r)
    out = []
    for key, group in sorted(groups.items()):
        a = dict(zip(KEYS, key))
        a['runs'] = len(group)
        for metric, value in group[0].items():
            if metric not in KEYS and metric not in ['seed', 'workload_sha256', 'case_id', 'config_sha256'] and isinstance(value, (int, float)):
                vals = [r[metric] for r in group]
                a[metric+'_mean'] = mean(vals)
                a[metric+'_sd'] = stdev(vals) if len(vals)>1 else 0.0
        out.append(a)
    return out


def select(rows, **filters):
    return [r for r in rows if all(r[k] == v for k, v in filters.items())]


def plot_all(rows, output):
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT/'results/.mplconfig'))
    os.environ.setdefault('XDG_CACHE_HOME', str(ROOT/'results/.cache'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size': 11, 'axes.spines.top': False, 'axes.spines.right': False})

    def finish(fig, name, caption):
        fig.text(.5,.012,caption,ha='center',fontsize=9)
        fig.tight_layout(rect=(0,.055,1,1))
        fig.savefig(output/(name+'.png'),dpi=190)
        plt.close(fig)

    lengths = sorted({r['length_m'] for r in rows if r['experiment']=='E1'})
    reads = sorted({r['read_s'] for r in rows if r['experiment']=='E1'})
    fig, axes = plt.subplots(1,len(lengths),figsize=(12,4.8),squeeze=False)
    for ax, length in zip(axes[0],lengths):
        for read in reads:
            group=sorted(select(rows,experiment='E1',length_m=length,read_s=read),key=lambda r:r['shuttles'])
            ax.errorbar([r['shuttles'] for r in group],[100*r['reader_busy_fraction_mean'] for r in group],yerr=[100*r['reader_busy_fraction_sd'] for r in group],marker='o',capsize=3,label=f'Optical read {read:g}s')
        ax.set(title=f'Rack lane {length:g} m',xlabel='Shuttles per ONE reader',ylabel='Reader busy time (%)',ylim=(0,105),xticks=[1,2,4,8])
        ax.legend(frameon=False)
    finish(fig,'fig1_provision','E1: Zone / B=4 / uniform batch. Busy = load + read + unload. Error bars: seed SD.')

    fig,axes=plt.subplots(1,2,figsize=(12,4.8))
    for ax,pattern in zip(axes,['uniform','hotspot']):
        for policy in LABELS:
            group=sorted(select(rows,experiment='E2',pattern=pattern,policy=policy),key=lambda r:r['shuttles'])
            ax.errorbar([r['shuttles'] for r in group],[r['throughput_req_s_mean']*60 for r in group],yerr=[r['throughput_req_s_sd']*60 for r in group],label=LABELS[policy],color=COLORS[policy],marker='o',capsize=3)
        ax.set(title=pattern,xlabel='Shuttles per ONE reader',ylabel='Read completions / min',xticks=[2,4,8])
        ax.legend(frameon=False,fontsize=9)
    finish(fig,'fig2_coordination','E2: identical hardware / 32 m / read=8s / B=4. Uniform and 75% two-row hotspot. Error bars: seed SD.')

    fig,axes=plt.subplots(1,2,figsize=(12,4.8))
    for ax,metric,title in zip(axes,['traffic_wait_s','pair_evaluations'],['Traffic waiting','Assignment search work']):
        for policy in LABELS:
            group=sorted(select(rows,experiment='E2',pattern='uniform',policy=policy),key=lambda r:r['shuttles'])
            ax.plot([r['shuttles'] for r in group],[r[metric+'_mean']/r['requests_mean'] for r in group],label=LABELS[policy],color=COLORS[policy],marker='o')
        ax.set(title=title,xlabel='Shuttles per ONE reader',ylabel='Shuttle-seconds / request' if metric=='traffic_wait_s' else 'Candidate pairs / request',xticks=[2,4,8])
        ax.legend(frameon=False,fontsize=9)
    finish(fig,'fig3_costs','E2 uniform: resource time and algorithm work, not measured controller hardware latency.')

    ns=sorted({r['shuttles'] for r in rows if r['experiment']=='E3'})
    fig,axes=plt.subplots(1,len(ns),figsize=(12,4.8),squeeze=False)
    for ax,n in zip(axes[0],ns):
        for policy in ['zone','nonzone_fifo']:
            group=sorted(select(rows,experiment='E3',shuttles=n,read_s=8,policy=policy),key=lambda r:r['buffer_slots'])
            ax.errorbar([r['buffer_slots'] for r in group],[r['throughput_req_s_mean']*60 for r in group],yerr=[r['throughput_req_s_sd']*60 for r in group],label=LABELS[policy],color=COLORS[policy],marker='o',capsize=3)
        ax.set(title=f'{n} shuttles / 1 reader',xlabel='Input waiting slots',ylabel='Read completions / min',xticks=[0,1,2,4])
        ax.legend(frameon=False)
    finish(fig,'fig4_buffer','E3: fixed hardware and routing; only input staging changes. 32 m / read=8s / uniform batch. Error bars: seed SD.')

    fig,axes=plt.subplots(1,2,figsize=(12,4.8))
    for ax,metric,title in zip(axes,['delivery_wait_s','reader_idle_demand_s'],['Shuttle blocked at handoff','Reader idle with waiting demand']):
        for policy in ['zone','nonzone_fifo']:
            group=sorted(select(rows,experiment='E3',shuttles=max(ns),read_s=8,policy=policy),key=lambda r:r['buffer_slots'])
            ax.plot([r['buffer_slots'] for r in group],[r[metric+'_mean']/r['requests_mean'] for r in group],label=LABELS[policy],color=COLORS[policy],marker='o')
        ax.set(title=title,xlabel='Input waiting slots',ylabel='Resource-seconds / request',xticks=[0,1,2,4])
        ax.legend(frameon=False)
    finish(fig,'fig5_handoff',f'E3: N={max(ns)}, read=8s. Parallel resource times must not be added as request latency.')

    fig,axes=plt.subplots(1,2,figsize=(12,4.8))
    for ax,pattern in zip(axes,['uniform','hotspot']):
        group=select(rows,experiment='E4',pattern=pattern)
        names=[f"{LABELS[r['policy']]}\nB={r['buffer_slots']}" for r in group]
        ax.bar(range(len(group)),[r['p99_s_mean']/60 for r in group],yerr=[r['p99_s_sd']/60 for r in group],capsize=3,color=[COLORS[r['policy']] for r in group])
        ax.set_xticks(range(len(group)),names,fontsize=9)
        ax.set(title=pattern,ylabel='Mean of run p99 (min)')
    finish(fig,'fig6_online','E4: paired Poisson arrivals, 60% of standalone reader ceiling; finite episodes, NOT steady-state p99.')


def report(rows, summary, out):
    lines=['# 單一 Partition：多 Shuttle、Zone/Non-Zone 與 Feeder Buffer', '',
           '本研究單位為一個實體 partition、一個 reader、8 條 rack rows，增加 shuttle 不增加 reader。Zone 是 partition 內部的服務分區。', '',
           '以下是受控模擬證據，不是實機測量或已完成的投稿論文。既有八 reader 實驗未混入。完整參數與無效／負向結果都保留。', '',
           f"共 {summary['run_count']} runs；每個 cell {len(summary['config']['seeds'])} seeds，每次 {summary['config']['requests']} requests。", '',
           '## 故事線與證據', '',
           '1. E1 檢查單一 shuttle 是否讓 reader 缺料，以及增加 shuttle 何時接近 reader 上限。平行搬運改善供料，不保證單趟 movement time 下降。',
           '2. E2 在相同 N 下比較 Zone、Non-Zone FIFO、有限 lookahead。Zone 的收集端仍共享 reader approach 與 gate，沒有免除交通檢查。',
           '3. E3 只改有限待讀 slots，量測交付阻塞與系統完成速率；buffer 不能消除道路瓶頸。',
           '4. E4 用配對 Poisson arrivals 檢查 batch 之外的場景；只有一個到達強度，非 workload 泛化證明。', '',
           '## 全矩陣（mean ± sample SD；p99 為每 run p99 的平均）', '',
           '| Exp | Pattern | N | Policy | B | Length | Read s | Busy % | req/min | p99 s |',
           '|---|---|---:|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append(f"| {r['experiment']} | {r['pattern']} | {r['shuttles']} | {r['policy']} | {r['buffer_slots']} | {r['length_m']} | {r['read_s']} | {100*r['reader_busy_fraction_mean']:.1f} ± {100*r['reader_busy_fraction_sd']:.1f} | {60*r['throughput_req_s_mean']:.3f} ± {60*r['throughput_req_s_sd']:.3f} | {r['p99_s_mean']:.1f} ± {r['p99_s_sd']:.1f} |")
    lines += ['', '## 模型與解讀限制', '',
              '- 合成 uniform/hotspot requests、固定讀取時間；所有需求一片一次，不做合併、cache 或預測 prefetch。',
              '- 固定 return-first；歸還路徑和時間完整計入，8 個有限 output slots。不最佳化 return。',
              '- 每段 connector 分別預約，Zone/Non-Zone 使用相同規則。離軌 docking bay 及 reader handoff 是宣告的硬體假設，沒有證明真實車體及 junction 幾何可行性。',
              '- Reader busy 包含 load/read/unload；optical fraction 另存 CSV。統計到最後一次 unload，不把最後 return drain 加入 reader utilization 分母。',
              '- Traffic wait、交付等待屬資源時間，不能直接相加當作使用者 latency。',
              '- Controller pair evaluations 是決策工作量 proxy，不是硬體 CPU 面積或量測延遲。',
              '- 總量、動作因果、路段互斥、shuttle/reader/gate 單資源互斥、buffer/output 容量與 latency 分解均檢查；不代表整個研究模型已被實機校準。',
              '- 若沒有觀察到「多一台更慢」，只能主張收益遞減／效率下降，不能用繪圖誇大成效能反轉。',
              '', '## Reproduce', '', '```bash', '.venv/bin/python scripts/run_partition_feeder_study.py --config experiments/partition-feeder-story/full.json', 'node scripts/build_partition_feeder_story.js', '```']
    (out/'ANALYSIS_ZH.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=ROOT/'experiments/partition-feeder-story/smoke.json')
    args=p.parse_args()
    raw=json.loads(args.config.read_text())
    if not raw['seeds'] or len(set(raw['seeds']))!=len(raw['seeds']):
        raise ValueError('Unique seeds required')
    out=ROOT/raw['output_dir']
    out.mkdir(parents=True,exist_ok=True)
    matrix=list(cases(raw))
    for _,_,_,c in matrix: c.validate()
    total=len(matrix)*len(raw['seeds'])
    print(f'Registered matrix: {total} runs; {raw["requests"]} requests/run',flush=True)
    rows, manifests=[],[]
    started=perf_counter()
    for seed in raw['seeds']:
        for i,(exp,pattern,rate,c) in enumerate(matrix):
            trace=make_requests(c,raw['requests'],seed,pattern,rate)
            sim=PartitionSimulation(c,trace)
            at=perf_counter()
            metrics,jobs,timeline=sim.run()
            case_id=f'{exp}-{seed}-{i:03d}'
            config_hash=hashlib.sha256(json.dumps(asdict(c),sort_keys=True).encode()).hexdigest()
            rows.append(dict(case_id=case_id,experiment=exp,pattern=pattern,arrival_mode='poisson' if rate else 'batch',
                             shuttles=c.shuttles,policy=c.policy,buffer_slots=c.buffer_slots,length_m=c.length_m,read_s=c.read_s,
                             seed=seed,config_sha256=config_hash,**metrics,cpu_wall_s=perf_counter()-at))
            manifests.append(dict(case_id=case_id,arrival_rate=rate,effective_config=asdict(c),config_sha256=config_hash))
            if seed==raw['seeds'][0] and exp=='E3' and c.shuttles==max(raw['buffer']['shuttles']) and c.read_s==8 and c.buffer_slots in [0,4]:
                audit=out/f'audit-{c.policy}-b{c.buffer_slots}'
                audit.mkdir(exist_ok=True)
                csv_write(audit/'requests.csv',[asdict(r) for r in trace])
                csv_write(audit/'jobs.csv',jobs)
                csv_write(audit/'timeline.csv',timeline)
                csv_write(audit/'rail.csv',sim.rail.records)
            if len(rows)%10==0 or len(rows)==total:
                print(f'{len(rows)}/{total} {exp} seed={seed}; wall={perf_counter()-started:.1f}s',flush=True)
    # Every mode/N/B in a matched workload must see identical requests.
    paired={}
    for row in rows:
        key=(row['seed'],row['pattern'],row['arrival_mode'],row['read_s'])
        paired.setdefault(key,set()).add(row['workload_sha256'])
    if any(len(v)!=1 for v in paired.values()):
        raise RuntimeError('Workload pairing failed')
    agg=aggregate(rows)
    csv_write(out/'runs.csv',rows)
    csv_write(out/'aggregate.csv',agg)
    sources=[ROOT/'glass_sim/partition_feeder_study.py',Path(__file__)]
    summary=dict(config=raw,run_count=len(rows),source_sha256={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sources},
                 config_sha256=hashlib.sha256(args.config.read_bytes()).hexdigest(),
                 validation=dict(all_read_and_returned=True,paired_requests=True,finite_staging=True,exclusive_resources=True,causal_service=True,latency_accounting=True),
                 simulation_wall_s=perf_counter()-started,python=sys.version)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (out/'run_configs.json').write_text(json.dumps(manifests,indent=2)+'\n')
    (out/'chart_data.json').write_text(json.dumps(dict(summary=summary,aggregate=agg),indent=2)+'\n')
    plot_all(agg,out)
    report(agg,summary,out)
    print(f'Complete: {total} runs, {perf_counter()-started:.1f}s, {out}',flush=True)


if __name__=='__main__': main()
