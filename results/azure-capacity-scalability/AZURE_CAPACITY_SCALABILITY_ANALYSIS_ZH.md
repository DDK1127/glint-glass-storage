# Azure Trace-driven Capacity Scalability

## 這次實驗回答什麼

固定 reader、shuttle 與 batch work，只增加 platter slots 與 rack physical footprint 時，同一批 Azure Blob accesses 是否會變慢？

## Dataset 與 mapping

- Dataset：Azure Functions Blob Access Trace 2020 的 deterministic head-100k read batch。
- 原始 batch：100,000 requests，跨 4.15 小時。
- 包含 79,751 unique blob versions；重複 version requests 為 20,249 (20.25%)。
- Batch-wide merge 後固定為 640 個 virtual platter services，讀取各 platter 上的 unique object bytes。
- 每個 scale 的 physical unique data 固定為 7218.9 MiB。
- Object-to-platter placement 是 deterministic uniform packing；Azure trace 沒有提供 Silica 實體 platter address。
- 原始 interarrival time 未放進 simulator；100,000 requests 在 batch 開始時共同可見。

## 主要結果

- Growing footprint 從 1x 增至 32x 時，throughput 保留 34.5%，損失 65.5%。
- Batch completion 從 29.74 分鐘增至 86.31 分鐘。
- 平均 movement time 增加 5.89x，最大規模占 cycle time 79.3%。
- Reader utilization 從 32.1% 降至 11.1%。
- Fixed-footprint control 在最大 slots 下仍保留 99.9% throughput。

## 解讀限制

這個結果使用 Azure 的 request identity、reuse 與 object sizes，但實體 platter placement 是 controlled mapping。它支持 physical reach 增長會讓 trace-calibrated batch 付出更多 transport time；不代表 Azure production placement，也不宣稱已包含 prefetch、collision 或 online arrivals。
