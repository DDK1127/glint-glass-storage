# Eight-zone sharing / feeder-buffer motivation experiment

## Scope

這是新建的受控離散事件模型，未沿用舊研究的結果。8 zones / 8 shuttles / 8 readers；固定位置、硬體與交通規則。數字僅代表此模型與合成負載，不是已校準的 Silica 預測。

獨立 saturated fixed/B=0 校準：256 requests，估計 finite-batch read drain rate 0.375081 req/s。這不是穩態容量估計；所有方法共用同一 arrival rate。

## Results

數值是各 run 的 p99 的平均，並非 pooled p99。誤差與逐次結果見 aggregate.csv / runs.csv。

| Pattern | Load factor | Mode | Group | Buffer slots | Mean p99 (s) | SD (s) | Delivery block / request (s) |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| hotspot | 0.65 | fixed | 1 | 0 | 469.45 | 53.10 | 0.24 |
| hotspot | 0.65 | fixed | 1 | 1 | 492.92 | 39.65 | 0.00 |
| hotspot | 0.65 | fixed | 1 | 4 | 492.92 | 39.65 | 0.00 |
| hotspot | 0.65 | joint | 2 | 0 | 1770.45 | 123.14 | 1.88 |
| hotspot | 0.65 | joint | 2 | 1 | 1878.52 | 193.59 | 0.11 |
| hotspot | 0.65 | joint | 2 | 4 | 1816.06 | 82.51 | 0.00 |
| hotspot | 0.65 | joint | 4 | 0 | 4992.76 | 96.42 | 2.84 |
| hotspot | 0.65 | joint | 4 | 1 | 4905.18 | 140.77 | 0.99 |
| hotspot | 0.65 | joint | 4 | 4 | 5087.27 | 87.37 | 0.06 |
| hotspot | 0.65 | joint | 8 | 0 | 8510.80 | 207.52 | 4.33 |
| hotspot | 0.65 | joint | 8 | 1 | 9092.98 | 183.31 | 1.40 |
| hotspot | 0.65 | joint | 8 | 4 | 8810.43 | 162.99 | 0.02 |
| hotspot | 0.65 | transport | 2 | 0 | 1701.43 | 126.67 | 1.99 |
| hotspot | 0.65 | transport | 2 | 1 | 1788.27 | 136.56 | 0.17 |
| hotspot | 0.65 | transport | 2 | 4 | 1627.82 | 51.39 | 0.00 |
| hotspot | 0.65 | transport | 4 | 0 | 4848.26 | 164.55 | 2.97 |
| hotspot | 0.65 | transport | 4 | 1 | 4854.54 | 110.00 | 1.04 |
| hotspot | 0.65 | transport | 4 | 4 | 4713.47 | 174.23 | 0.26 |
| hotspot | 0.65 | transport | 8 | 0 | 8336.99 | 493.36 | 4.79 |
| hotspot | 0.65 | transport | 8 | 1 | 8905.80 | 239.51 | 1.21 |
| hotspot | 0.65 | transport | 8 | 4 | 8676.21 | 301.69 | 0.40 |
| hotspot | 0.9 | fixed | 1 | 0 | 672.85 | 19.19 | 0.23 |
| hotspot | 0.9 | fixed | 1 | 1 | 701.61 | 27.55 | 0.00 |
| hotspot | 0.9 | fixed | 1 | 4 | 701.61 | 27.55 | 0.00 |
| hotspot | 0.9 | joint | 2 | 0 | 2352.24 | 152.25 | 1.88 |
| hotspot | 0.9 | joint | 2 | 1 | 2312.81 | 121.52 | 0.17 |
| hotspot | 0.9 | joint | 2 | 4 | 2241.54 | 316.07 | 0.00 |
| hotspot | 0.9 | joint | 4 | 0 | 5423.52 | 213.77 | 2.91 |
| hotspot | 0.9 | joint | 4 | 1 | 5442.35 | 94.81 | 0.94 |
| hotspot | 0.9 | joint | 4 | 4 | 5826.38 | 35.11 | 0.05 |
| hotspot | 0.9 | joint | 8 | 0 | 8987.99 | 205.28 | 4.01 |
| hotspot | 0.9 | joint | 8 | 1 | 9264.12 | 80.72 | 1.56 |
| hotspot | 0.9 | joint | 8 | 4 | 9321.98 | 204.12 | 0.05 |
| hotspot | 0.9 | transport | 2 | 0 | 2378.76 | 91.73 | 1.97 |
| hotspot | 0.9 | transport | 2 | 1 | 2134.01 | 41.18 | 0.09 |
| hotspot | 0.9 | transport | 2 | 4 | 2234.66 | 195.87 | 0.00 |
| hotspot | 0.9 | transport | 4 | 0 | 5358.62 | 125.28 | 3.39 |
| hotspot | 0.9 | transport | 4 | 1 | 5284.20 | 366.76 | 1.12 |
| hotspot | 0.9 | transport | 4 | 4 | 5353.35 | 26.93 | 0.49 |
| hotspot | 0.9 | transport | 8 | 0 | 8777.52 | 264.37 | 4.36 |
| hotspot | 0.9 | transport | 8 | 1 | 8951.63 | 191.06 | 1.50 |
| hotspot | 0.9 | transport | 8 | 4 | 9250.89 | 127.87 | 0.03 |
| uniform | 0.65 | fixed | 1 | 0 | 108.98 | 34.42 | 0.29 |
| uniform | 0.65 | fixed | 1 | 1 | 113.00 | 28.42 | 0.00 |
| uniform | 0.65 | fixed | 1 | 4 | 113.00 | 28.42 | 0.00 |
| uniform | 0.65 | joint | 2 | 0 | 2072.57 | 160.07 | 2.07 |
| uniform | 0.65 | joint | 2 | 1 | 1963.69 | 89.67 | 0.16 |
| uniform | 0.65 | joint | 2 | 4 | 1813.37 | 148.95 | 0.00 |
| uniform | 0.65 | joint | 4 | 0 | 5286.75 | 225.04 | 2.51 |
| uniform | 0.65 | joint | 4 | 1 | 5212.42 | 236.74 | 0.60 |
| uniform | 0.65 | joint | 4 | 4 | 5188.64 | 174.16 | 0.00 |
| uniform | 0.65 | joint | 8 | 0 | 9106.77 | 257.43 | 3.20 |
| uniform | 0.65 | joint | 8 | 1 | 9577.83 | 429.41 | 0.44 |
| uniform | 0.65 | joint | 8 | 4 | 9586.44 | 105.19 | 0.00 |
| uniform | 0.65 | transport | 2 | 0 | 2032.78 | 186.96 | 2.45 |
| uniform | 0.65 | transport | 2 | 1 | 1954.09 | 166.64 | 0.18 |
| uniform | 0.65 | transport | 2 | 4 | 1869.64 | 136.93 | 0.00 |
| uniform | 0.65 | transport | 4 | 0 | 5292.79 | 208.21 | 2.60 |
| uniform | 0.65 | transport | 4 | 1 | 5221.65 | 219.33 | 0.61 |
| uniform | 0.65 | transport | 4 | 4 | 5111.11 | 76.46 | 0.00 |
| uniform | 0.65 | transport | 8 | 0 | 9106.77 | 257.43 | 3.20 |
| uniform | 0.65 | transport | 8 | 1 | 9577.83 | 429.41 | 0.44 |
| uniform | 0.65 | transport | 8 | 4 | 9625.73 | 39.49 | 0.00 |
| uniform | 0.9 | fixed | 1 | 0 | 168.00 | 31.20 | 0.24 |
| uniform | 0.9 | fixed | 1 | 1 | 177.59 | 23.71 | 0.00 |
| uniform | 0.9 | fixed | 1 | 4 | 177.59 | 23.71 | 0.00 |
| uniform | 0.9 | joint | 2 | 0 | 2675.40 | 224.12 | 2.59 |
| uniform | 0.9 | joint | 2 | 1 | 2392.33 | 186.60 | 0.23 |
| uniform | 0.9 | joint | 2 | 4 | 2312.44 | 129.22 | 0.00 |
| uniform | 0.9 | joint | 4 | 0 | 5766.96 | 372.22 | 2.36 |
| uniform | 0.9 | joint | 4 | 1 | 5774.79 | 239.94 | 0.52 |
| uniform | 0.9 | joint | 4 | 4 | 5685.78 | 103.14 | 0.00 |
| uniform | 0.9 | joint | 8 | 0 | 9555.20 | 95.29 | 3.31 |
| uniform | 0.9 | joint | 8 | 1 | 9885.66 | 594.48 | 0.77 |
| uniform | 0.9 | joint | 8 | 4 | 10142.56 | 247.49 | 0.00 |
| uniform | 0.9 | transport | 2 | 0 | 2639.03 | 126.85 | 2.68 |
| uniform | 0.9 | transport | 2 | 1 | 2378.61 | 152.79 | 0.18 |
| uniform | 0.9 | transport | 2 | 4 | 2349.87 | 217.24 | 0.00 |
| uniform | 0.9 | transport | 4 | 0 | 5762.25 | 371.40 | 2.37 |
| uniform | 0.9 | transport | 4 | 1 | 5721.31 | 201.19 | 0.49 |
| uniform | 0.9 | transport | 4 | 4 | 5715.81 | 59.47 | 0.01 |
| uniform | 0.9 | transport | 8 | 0 | 9513.98 | 165.49 | 3.42 |
| uniform | 0.9 | transport | 8 | 1 | 9885.66 | 594.48 | 0.77 |
| uniform | 0.9 | transport | 8 | 4 | 10180.40 | 184.97 | 0.00 |

## Evidence boundary

- Synthetic equal-size requests; one physical fetch/read/return per request. No online merge, cache, prefetch or future-arrival knowledge.
- Middle-third hotspot puts 65% of requests in zones 3/4. Timing and local slot draws are paired with uniform workload; each method gets the identical trace within a case.
- Local lanes and a single shared trunk are exclusive. Entire routes reserve all required resources for their duration. This conservative topology can dominate cross-zone sharing; results do not generalize to alternative rail networks.
- Eight finite off-rail shuttle bays per zone are provisioned in every case (64 total). A bay accommodates the shuttle, including a carried platter; it is not a feeder slot. This generous fixed provision avoids unmodeled on-rail parking but is a hardware assumption.
- Each reader has one finite output slot. A full output blocks unloading; returns have dispatch priority. No unlimited return staging.
- Input capacity excludes the mounted platter and the output slot. B=0 uses direct handoff; a waiting shuttle remains occupied at a dock. The same local handoff mechanism and costs exist for every B.
- Return service is charged and every platter goes home. Request completion excludes its own unload/return, which can delay later requests.
- Transport sharing uses contiguous home groups. Joint sharing adds reader eligibility within the same group. Glass never moves between physically disconnected components.
- Controller: returns first, then oldest currently feasible request; earliest estimated pickup shuttle; joint mode chooses estimated earliest completion reader including committed in-flight work. Finite-buffer release and output blockage are only approximately predicted, not optimized.
- Excluded-work idle time is an upper-bound opportunity indicator, not proof that helping would improve completion. Demand-free reader idle is excluded from the starvation indicator.
- Sharing groups 2/4/8 also change which hotspot zones can cooperate (zones 3/4 straddle the group boundary for 2/4). Group-size effects cannot be attributed solely to the number of eligible robots; balanced and shifted partitions are a follow-up sensitivity.
- Fixed-duration mechanics and one finite workload episode: no real-trace generalization, no confidence claim from three seeds, no cost/energy claim or novel-algorithm claim.

## Reproduce

```bash
.venv/bin/python scripts/run_sharing_buffer_study.py --config experiments/sharing-buffer/full.json
```

Audit CSVs retain requests, complete jobs, shuttle/reader timeline and transport reservations for the first seed of the hotspot higher-load cases. Figures are PNG; no PDF export required.
