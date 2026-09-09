# LUN0 Address-Mapped Static-Zone Experiment

## 實驗做法

- 使用完整 `2016022211-LUN0.csv` 的 observed read-address range，事先切成 8 個等 address-range、連續且不重疊的 static zones。
- 每個 64 MiB address stripe 固定映射到 6,400 個 panel positions 之一。
- 評估 timestamp 排序後最前面的 100,000 筆 reads；沒有修改 request order、offset、size 或熱門程度。
- 所有 requests 視為同一 batch，映射後才對同一 platter 做 merge。
- 不包含 hash placement、application affinity、adaptive boundary 或 work stealing。

## 結果

- Balanced reference：每個 zone 應承擔 12.5% work。
- 最忙 zone 的原始 requests：31.99% （平均的 2.56x）。
- Merge 後最忙 zone 的 physical work：29.91% （平均的 2.39x）。
- Physical platter tasks：1,366，平均每次 service 合併 73.21 requests。
- Static capacity efficiency：41.79%。
- Throughput loss vs. same-work ideal：58.21%。
- Batch drain time：3.48 hours。

## 解讀邊界

這個結果直接衡量 LUN address locality 在固定 contiguous zones 下造成的失衡。Zone boundaries 使用完整 trace 的 observed range，因此不會隨這個 batch 調整。

但 LUN offset 仍是 logical address，不是 Microsoft 公開的真實 Silica platter placement；contiguous address-to-position mapping 是本實驗明確採用的 placement assumption。
