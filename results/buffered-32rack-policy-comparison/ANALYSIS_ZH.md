# Fixed 32-Rack Feeder-Buffer Study

## Setup

All policies use the same 32 racks × 16 m, 1 m rack spacing, 8 readers, Azure arrivals, and paired platter placement. Static Zone uses 8 end-to-end shuttles without buffers. Rack-local Zone and Shared No-Zone use 32 rack shuttles, 8 fixed reader-side loaders, and four input staging slots per reader.

| Policy | Mean latency | p99 latency | Throughput | Reader utilization | Conflict wait / service | Buffer wait / service |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Static Zone | 24.28 min | 52.04 min | 5.48 req/s | 18.9% | 0.00 s | 0.00 s |
| Rack-local Zone | 4.93 min | 12.38 min | 6.39 req/s | 96.5% | 0.00 s | 20.04 s |
| Shared No-Zone | 39.18 min | 76.71 min | 5.12 req/s | 12.2% | 139.45 s | 24.01 s |

## 主要觀察

Static Zone 使用 8 個 end-to-end shuttles，每台負責 4 racks，p99 為 52.04 分鐘。它沒有 feeder buffer，作為原始 8-zone 架構基準。

Rack-local Zone 的 p99 為 12.38 分鐘，reader utilization 達 96.5%。四-slot feeder buffers 已將 32 條 rack-local retrieval streams 平滑地供應給 8 readers；buffer queue 在這裡代表 reader 接近飽和，而不是 reader starvation。

Shared No-Zone 有 96.4% fetch 由非本 rack shuttle 執行，平均 transport movement 從 Zone 的 16.8 秒/service 增加到 80.8 秒/service。再加上 139.4 秒/service 的 conflict waiting，p99 上升到 76.71 分鐘，reader utilization 降到 12.2%。

Rack-local Zone 相對 Static 的差異同時包含更多 rack shuttles與 feeder-buffer handoff；這是 architecture comparison，不是單一 scheduling ablation。Static movement 為 23.4 秒/service，Rack-local Zone 為 16.8 秒/service。

這個固定配置中，每個 rack 已有一台 shuttle，shared ownership 幾乎沒有額外 capacity 可以回收。Rack-local Zone + feeder buffer 反而同時保留 local movement 並讓 readers 持續有 platter 可讀。

## Model boundary

- Static Zone has 8 end-to-end shuttles and no feeder buffer; Rack-local Zone has 32 rack shuttles plus 8 fixed reader-side loaders.
- Rack-local Zone has one dedicated shuttle per rack and assumes dedicated rack movement is conflict-free.
- Rack centerlines are 1 m apart, larger than the 0.65 m clearance; cross-rack paths can still intersect during vertical movement.
- Shared No-Zone uses the same oldest-request/nearest-shuttle dispatch and direct routes, but waits behind prior space-time reservations.
- The input buffer has four slots per reader. Waiting outside a full buffer is an optimistic off-rail hold.
- Output staging is bounded indirectly by prioritizing returns once 32 completed platters are waiting.
- Reader-side loader movement is abstracted into serialized reader load/unload time; it is not a separately routed robot.
