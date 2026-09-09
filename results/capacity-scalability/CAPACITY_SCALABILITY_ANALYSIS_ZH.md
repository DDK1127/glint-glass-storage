# Capacity Scalability Pilot

## 問題

固定 reader 與 shuttle 數量時，增加 platter slots、storage racks 與 panel 長度，是否會因 shuttle transport 增加而降低效能？

## 控制條件

- 固定 8 readers 與 8 shuttles。
- 每次固定 640 個互不重複的 64 MiB platter tasks。
- 每個 service lane 恰好分配 80 個 tasks。
- 測試 storage-rack scale：1, 2, 4, 8, 16, 32。
- `fixed_footprint_control`：slots 增加，但 half-panel 長度固定。
- `growing_footprint`：slots 與 half-panel 長度隨 rack 數同比增加。
- 所有 scales 使用 paired normalized locations；不包含 skew、merge、request reordering、collision 或 controller CPU cost。

## 主要結果

- 最大規模相對最小規模增加 32x racks、32x platter slots 與 32x physical length。
- Growing-footprint throughput 保留 35.3%，損失 64.7%。
- 平均 shuttle movement time 增加為 5.91x，在最大規模占 cycle time 78.2%。
- Reader utilization 從 34.8% 降至 12.3%。
- 本輪固定每筆 request 為 64 MiB；每片 platter 的 reader read time 平均為 2.07 秒。真實 read time 會隨 request bytes 改變。
- Reader load/unload 固定為 6.00 秒。Reader read 與 load/unload 合計占完整 cycle 的比例從 35.7% 降至 12.5%。
- 固定 footprint control 在最大 platter count 仍保留 99.9% throughput。

## 解讀

這個 pilot 支持的結論不是『platter 數量本身會降低效能』，而是：當增加 platter capacity 同時擴大 physical footprint，固定數量的 reader/shuttle service lanes 會花更多 cycle time 在 media transport，降低 reader 的有效使用率與 batch throughput。

## 限制

- 每個 reader 與 shuttle 被建模為一條 direct fetch/read/return service lane。
- 未建模 shuttle collision、共享 feeder buffer、reader reassignment 或 prefetch。
- Controller 排程成本設為零，因此觀察到的退化只來自物理 movement。
- 結果是 mechanism pilot，不是 production Silica capacity forecast。

## Figure guide

- `fig1_capacity_scaling_performance`：固定 footprint control 與 growing footprint 的效能差異。
- `fig2_why_capacity_scaling_degrades`：movement time 增加與 reader utilization 下降。
- `fig3_time_breakdown`：每片 platter 的 shuttle movement、reader read、reader load/unload 與 platter pick/place 時間及其占比。
