# N=8 Prefetch Buffer Sweep

這一輪固定單一 partition、單一 reader、8 台 shuttle；只改 feeder-buffer capacity = 0/8/16。B>0 代表 request 已知後，reader 忙碌時把下一批 glass 先送到 buffer。它不是未知 request 的 speculative prefetch，也不是 read-after-read cache。

## Results

| Pattern | Read s | Policy | B | Prefetch hit | Lead s | Route motion / request | Traffic wait / request | Mean p99 min | Throughput req/min |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| hotspot | 2 | nonzone_fifo | 0 | 0.0% | 0.0 | 53.96 | 105.46 | 135.51 | 2.800 |
| hotspot | 2 | nonzone_fifo | 8 | 16.6% | 2.0 | 53.99 | 110.21 | 139.90 | 2.717 |
| hotspot | 2 | nonzone_fifo | 16 | 16.6% | 2.0 | 53.99 | 110.21 | 139.90 | 2.717 |
| hotspot | 2 | zone | 0 | 0.0% | 0.0 | 47.34 | 5.45 | 166.23 | 2.267 |
| hotspot | 2 | zone | 8 | 21.5% | 3.5 | 47.32 | 6.03 | 165.38 | 2.279 |
| hotspot | 2 | zone | 16 | 21.5% | 3.5 | 47.32 | 6.03 | 165.38 | 2.279 |
| hotspot | 8 | nonzone_fifo | 0 | 0.0% | 0.0 | 54.56 | 96.24 | 131.21 | 2.895 |
| hotspot | 8 | nonzone_fifo | 8 | 43.2% | 8.2 | 53.63 | 109.04 | 139.25 | 2.719 |
| hotspot | 8 | nonzone_fifo | 16 | 43.2% | 8.2 | 53.63 | 109.04 | 139.25 | 2.719 |
| hotspot | 8 | zone | 0 | 0.0% | 0.0 | 47.29 | 4.52 | 173.58 | 2.172 |
| hotspot | 8 | zone | 8 | 43.8% | 60.2 | 46.57 | 4.45 | 167.94 | 2.242 |
| hotspot | 8 | zone | 16 | 44.7% | 112.9 | 46.58 | 4.60 | 167.84 | 2.244 |
| hotspot | 24 | nonzone_fifo | 0 | 0.0% | 0.0 | 54.94 | 24.73 | 178.07 | 2.135 |
| hotspot | 24 | nonzone_fifo | 8 | 99.7% | 211.0 | 54.51 | 28.87 | 171.75 | 2.214 |
| hotspot | 24 | nonzone_fifo | 16 | 99.7% | 411.7 | 53.87 | 34.10 | 171.75 | 2.214 |
| hotspot | 24 | zone | 0 | 0.0% | 0.0 | 43.46 | 2.14 | 199.79 | 1.891 |
| hotspot | 24 | zone | 8 | 84.3% | 120.1 | 44.81 | 3.17 | 187.70 | 2.010 |
| hotspot | 24 | zone | 16 | 86.2% | 242.1 | 44.99 | 3.24 | 185.94 | 2.028 |
| uniform | 2 | nonzone_fifo | 0 | 0.0% | 0.0 | 54.60 | 43.19 | 86.41 | 4.394 |
| uniform | 2 | nonzone_fifo | 8 | 29.7% | 2.8 | 53.18 | 44.42 | 87.08 | 4.358 |
| uniform | 2 | nonzone_fifo | 16 | 29.7% | 2.8 | 53.18 | 44.42 | 87.08 | 4.358 |
| uniform | 2 | zone | 0 | 0.0% | 0.0 | 44.56 | 8.89 | 67.12 | 5.518 |
| uniform | 2 | zone | 8 | 47.6% | 3.7 | 44.60 | 9.72 | 66.09 | 5.585 |
| uniform | 2 | zone | 16 | 47.6% | 3.7 | 44.60 | 9.72 | 66.09 | 5.585 |
| uniform | 8 | nonzone_fifo | 0 | 0.0% | 0.0 | 55.74 | 37.43 | 89.41 | 4.247 |
| uniform | 8 | nonzone_fifo | 8 | 75.7% | 16.6 | 52.97 | 44.27 | 86.96 | 4.364 |
| uniform | 8 | nonzone_fifo | 16 | 75.6% | 15.9 | 53.01 | 44.16 | 86.76 | 4.372 |
| uniform | 8 | zone | 0 | 0.0% | 0.0 | 44.47 | 5.59 | 84.14 | 4.432 |
| uniform | 8 | zone | 8 | 95.4% | 82.1 | 42.40 | 4.71 | 76.29 | 4.879 |
| uniform | 8 | zone | 16 | 96.7% | 165.0 | 41.76 | 4.46 | 75.32 | 4.902 |
| uniform | 24 | nonzone_fifo | 0 | 0.0% | 0.0 | 57.29 | 9.41 | 177.94 | 2.137 |
| uniform | 24 | nonzone_fifo | 8 | 99.7% | 212.4 | 56.45 | 10.88 | 171.62 | 2.215 |
| uniform | 24 | nonzone_fifo | 16 | 99.7% | 419.6 | 55.51 | 11.68 | 171.62 | 2.215 |
| uniform | 24 | zone | 0 | 0.0% | 0.0 | 40.92 | 1.05 | 179.19 | 2.109 |
| uniform | 24 | zone | 8 | 99.4% | 212.1 | 40.88 | 1.29 | 172.10 | 2.204 |
| uniform | 24 | zone | 16 | 99.6% | 419.4 | 40.92 | 1.37 | 171.36 | 2.205 |

## How to read this experiment

- `prefetch_hit_fraction` and `prefetch_lead_mean_s` quantify overlap: the glass reached handoff before its reader service started.
- `route_motion_s` is still present under B=8/16. Prefetch hides route work behind reader service; it does not shorten one physical trip.
- `traffic_wait_s` is separate from route motion. A large value means N=8 shuttles compete for the partition's rail resources.
- B=16 tests capacity beyond the one-slot-per-shuttle design point; it may improve absorption of bursts, but it can also hold stale/early work and increase waiting.
- All rows use the same 5 seeds, request count, placement generator, partition and reader. P99 is the mean of five per-run p99 values, not a pooled quantile.

## Scope boundary

This is a controlled motivation experiment. It does not claim a calibrated Project Silica throughput, a globally optimal prefetch policy, or a universal optimal N. Return uses the fixed return-first policy from the parent study. See `experiments/partition-feeder-story/README.md` for transport, handoff, output and causal assumptions.

## Reproduce

```bash
.venv/bin/python scripts/run_prefetch_n8.py --config experiments/partition-feeder-story/prefetch-n8.json
```
